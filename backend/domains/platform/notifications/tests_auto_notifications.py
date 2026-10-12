import datetime
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from domains.money.payments.models import Payment
from domains.money.subscriptions.models import Subscription
from domains.money.subscriptions.subscription_types import create_type
from domains.people.clients.models import Child, ChildContact, ParentContact
from domains.platform.notifications.messaging import automation, service
from domains.platform.notifications.models import (
    MessageCategory,
    MessagingConsent,
    OutboundMessage,
)
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.tenants.org_settings import (
    AUTO_NOTIFY_LESSON_CHANGES_ENABLED,
    AUTO_NOTIFY_PAYMENT_ENABLED,
    AUTO_NOTIFY_SUBSCRIPTION_ENABLED,
)
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.schedule.models import Lesson


class AutoNotificationTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="tru-171")
        self.branch = Branch.objects.create(organization=self.org, name="Главный")
        self.direction = Direction.objects.create(organization=self.org, name="Балет")
        self.owner = User.objects.create_user(
            phone="+77010000001",
            password="p",
            full_name="Владелец",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.child = Child.objects.create(
            organization=self.org,
            full_name="Алия Тестова",
            birth_date=datetime.date(2017, 1, 1),
            gender=Child.Gender.FEMALE,
        )
        self.payer = self._parent("Плательщик", True)
        self.other = self._parent("Другой контакт", False)
        self.group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Балет 7–9",
            capacity=12,
        )
        GroupMembership.objects.create(
            organization=self.org,
            group=self.group,
            child=self.child,
            joined_at=timezone.localdate() - datetime.timedelta(days=30),
        )

    def _parent(self, name, payer):
        parent = ParentContact.objects.create(organization=self.org, full_name=name)
        ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=parent,
            role=ChildContact.Role.MOTHER if payer else ChildContact.Role.FATHER,
            is_payer=payer,
        )
        service.set_consent(
            parent,
            MessageCategory.UTILITY,
            MessagingConsent.Status.OPTED_IN,
            MessagingConsent.Source.ADMIN_FORM,
        )
        return parent

    def _subscription(self):
        kind = create_type(
            self.org,
            name="8 занятий",
            price=Decimal("25000"),
            quota_sessions=8,
            duration_days=30,
        )
        return Subscription.objects.create(
            organization=self.org,
            child=self.child,
            subscription_type_version=kind.versions.latest(),
            direction=self.direction,
            branch=self.branch,
            starts_on=timezone.localdate() - datetime.timedelta(days=20),
            ends_on=timezone.localdate() + datetime.timedelta(days=3),
            sessions_remaining_cache=2,
            list_price=Decimal("25000"),
            price=Decimal("25000"),
        )

    @mock.patch("domains.platform.notifications.messaging.automation.notify")
    def test_payment_goes_to_payment_payer_not_every_contact(self, notify):
        self.org.settings = {
            AUTO_NOTIFY_PAYMENT_ENABLED: True,
            AUTO_NOTIFY_SUBSCRIPTION_ENABLED: False,
        }
        self.org.save(update_fields=["settings"])
        subscription = self._subscription()
        Payment.objects.create(
            organization=self.org,
            subscription=subscription,
            amount=Decimal("1000"),
            method=Payment.Method.CASH,
            status=Payment.Status.CONFIRMED,
            payer=self.payer,
            received_by=self.owner,
        )

        automation.dispatch_daily_for_organization(self.org)

        payment_calls = [call for call in notify.call_args_list if call.args[1] == "payment_due"]
        self.assertEqual([call.args[0] for call in payment_calls], [self.payer])

    def test_cancel_queues_notification_after_debounce(self):
        starts = timezone.now() + datetime.timedelta(days=2)
        lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            starts_at=starts,
            ends_at=starts + datetime.timedelta(hours=1),
        )
        with mock.patch(
            "domains.platform.notifications.messaging.tasks."
            "dispatch_lesson_change_notification.apply_async"
        ) as queued:
            with self.captureOnCommitCallbacks(execute=True):
                lesson.cancel(actor=self.owner, category="other", comment="Ремонт зала")
        queued.assert_called_once()
        self.assertEqual(queued.call_args.kwargs["args"], [str(lesson.id)])

    @mock.patch("domains.platform.notifications.messaging.automation.notify")
    def test_bulk_changes_are_one_message_per_child_and_day(self, notify):
        self.org.settings = {AUTO_NOTIFY_LESSON_CHANGES_ENABLED: True}
        self.org.save(update_fields=["settings"])
        starts = timezone.now() + datetime.timedelta(days=2)
        lessons = []
        for offset in (0, 2):
            lesson = Lesson.objects.create(
                organization=self.org,
                group=self.group,
                starts_at=starts + datetime.timedelta(hours=offset),
                ends_at=starts + datetime.timedelta(hours=offset + 1),
            )
            Lesson.objects.filter(pk=lesson.pk).update(
                status=Lesson.Status.CANCELLED,
                cancel_reason="Праздник",
            )
            lesson.refresh_from_db()
            lessons.append(lesson)

        automation.dispatch_lesson_change(lessons[0].id)

        self.assertEqual(notify.call_count, 2)  # одно каждому из двух родителей
        self.assertTrue(all(call.args[1] == "lesson_cancelled" for call in notify.call_args_list))
        self.assertTrue(
            all(
                call.kwargs["dedup_key"].startswith("auto:lesson-change:")
                for call in notify.call_args_list
            )
        )
        self.assertIn("Праздник", notify.call_args_list[0].args[2]["changes"])

    def test_settings_api_returns_weekly_preview(self):
        client = APIClient()
        client.force_authenticate(self.owner)
        response = client.get("/api/v1/messaging/settings/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("rules", response.data)
        self.assertIn("weekly_preview", response.data)

    @mock.patch("domains.platform.notifications.messaging.automation.notify")
    def test_reverted_cancellation_is_not_sent(self, notify):
        self.org.settings = {AUTO_NOTIFY_LESSON_CHANGES_ENABLED: True}
        self.org.save(update_fields=["settings"])
        starts = timezone.now() + datetime.timedelta(days=2)
        lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            starts_at=starts,
            ends_at=starts + datetime.timedelta(hours=1),
        )
        Lesson.objects.filter(pk=lesson.pk).update(status=Lesson.Status.CANCELLED)
        Lesson.objects.filter(pk=lesson.pk).update(status=Lesson.Status.SCHEDULED)

        self.assertEqual(automation.dispatch_lesson_change(lesson.id), 0)
        notify.assert_not_called()

    @mock.patch("domains.platform.notifications.messaging.tasks.deliver_message.delay")
    def test_subscription_notification_is_not_duplicated(self, deliver):
        self.org.settings = {
            AUTO_NOTIFY_PAYMENT_ENABLED: False,
            AUTO_NOTIFY_SUBSCRIPTION_ENABLED: True,
        }
        self.org.save(update_fields=["settings"])
        subscription = self._subscription()

        with self.captureOnCommitCallbacks(execute=True):
            automation.dispatch_daily_for_organization(self.org)
            automation.dispatch_daily_for_organization(self.org)

        rows = OutboundMessage.objects.filter(
            organization=self.org,
            event="subscription_ending",
            dedup_key__startswith=f"auto:subscription:{subscription.id}:",
        )
        self.assertEqual(rows.count(), 2)
        self.assertEqual(rows.values("parent_id").distinct().count(), 2)
        self.assertEqual(deliver.call_count, 2)

    @mock.patch("domains.platform.notifications.messaging.tasks.deliver_message.delay")
    def test_payment_notification_is_not_repeated_daily(self, deliver):
        self.org.settings = {
            AUTO_NOTIFY_PAYMENT_ENABLED: True,
            AUTO_NOTIFY_SUBSCRIPTION_ENABLED: False,
        }
        self.org.save(update_fields=["settings"])
        subscription = self._subscription()
        Payment.objects.create(
            organization=self.org,
            subscription=subscription,
            amount=Decimal("1000"),
            method=Payment.Method.CASH,
            status=Payment.Status.CONFIRMED,
            payer=self.payer,
            received_by=self.owner,
        )

        with self.captureOnCommitCallbacks(execute=True):
            automation.dispatch_daily_for_organization(self.org)
            automation.dispatch_daily_for_organization(
                self.org, today=timezone.localdate() + datetime.timedelta(days=1)
            )

        rows = OutboundMessage.objects.filter(
            organization=self.org,
            event="payment_due",
            dedup_key=f"auto:payment:{subscription.id}:{self.payer.id}",
        )
        self.assertEqual(rows.count(), 1)
        self.assertEqual(deliver.call_count, 1)
