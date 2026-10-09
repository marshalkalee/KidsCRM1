"""Центр рассылок родителям (TRU-168): контракт notify()."""

import datetime
import pathlib
import re
from unittest import mock
from zoneinfo import ZoneInfo

from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from domains.people.clients.models import ContactPhone, ParentContact
from domains.people.portal.models import ParentAccount
from domains.platform.core.audit import AuditLog
from domains.platform.tenants.models import Organization
from domains.platform.users.models import User

from .messaging import service
from .messaging.channels import EmailChannel
from .models import MessageCategory, MessageTemplate, MessagingConsent, OutboundMessage

ALMATY = ZoneInfo("Asia/Almaty")
NOON = datetime.datetime(2026, 10, 7, 12, 0, tzinfo=ALMATY)
UTILITY = MessageCategory.UTILITY
Status = OutboundMessage.Status


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    MESSAGING_FROM_EMAIL="noreply@kidscrm.kz",
    PUBLIC_BASE_URL="https://app.kidscrm.kz",
)
class MessagingFixtures(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="tb-msg")
        self.parent = ParentContact.objects.create(
            organization=self.org, full_name="Сапарова Айгерим", email="aigerim@example.kz"
        )
        ContactPhone.objects.create(
            organization=self.org, parent_contact=self.parent, number="+77011112233"
        )
        self.owner = self.user("77010000001", User.Role.OWNER)
        self.delay = mock.patch(
            "domains.platform.notifications.messaging.tasks.deliver_message.delay"
        ).start()
        self.later = mock.patch(
            "domains.platform.notifications.messaging.tasks.deliver_message.apply_async"
        ).start()
        self.addCleanup(mock.patch.stopall)

    def user(self, phone, role):
        return User.objects.create_user(
            phone=phone, password="p", full_name=role, organization=self.org, role=role
        )

    def api(self, user=None):
        client = APIClient()
        client.force_authenticate(user=user or self.owner)
        return client

    def consent(
        self, status=MessagingConsent.Status.OPTED_IN, category=UTILITY, source="admin_form"
    ):
        return service.set_consent(self.parent, category, status, source, user=self.owner)

    def notify(self, key="payment_due:1", event="payment_due", **context):
        with self.captureOnCommitCallbacks(execute=True):
            return service.notify(
                self.parent,
                event,
                {"child": "Алия", "amount": "25 000 ₸", **context},
                dedup_key=key,
            )

    def deliver(self, message, now=NOON):
        return service.deliver(message.id, now=now)


class NotifyContractTests(MessagingFixtures):
    def test_same_event_twice_is_one_message(self):
        first = self.notify()
        second = self.notify()
        self.assertEqual(first.id, second.id)
        self.assertEqual(OutboundMessage.objects.count(), 1)
        self.delay.assert_called_once_with(str(first.id))

    def test_unknown_event_is_a_programming_error(self):
        with self.assertRaises(service.MessagingError):
            service.notify(self.parent, "nope", {}, dedup_key="x")

    def test_no_consent_means_no_message(self):
        message = self.deliver(self.notify())
        self.assertEqual(message.status, Status.NO_CONSENT)
        self.assertEqual(mail.outbox, [])

    def test_opt_out_wins(self):
        self.consent(MessagingConsent.Status.OPTED_OUT)
        self.assertEqual(self.deliver(self.notify()).status, Status.OPTED_OUT)
        self.assertEqual(mail.outbox, [])

    def test_email_end_to_end(self):
        self.consent()
        message = self.deliver(self.notify())
        self.assertEqual(message.status, Status.SENT)
        self.assertEqual(message.channel, "email")
        sent = mail.outbox[0]
        self.assertEqual(sent.to, ["aigerim@example.kz"])
        self.assertEqual(sent.subject, "True Ballet: напоминание об оплате")
        self.assertIn("Здравствуйте, Айгерим!", sent.body)
        self.assertIn("Алия: к оплате 25 000 ₸", sent.body)
        self.assertEqual(sent.from_email, "True Ballet <noreply@kidscrm.kz>")
        self.assertIn("https://app.kidscrm.kz/api/v1/messaging/unsubscribe/", sent.body)
        self.assertIn("List-Unsubscribe", sent.extra_headers)
        # В журнале — ровно то, что ушло.
        self.assertEqual(message.body, sent.body)

    def test_kazakh_for_parent_with_kazakh_cabinet(self):
        ParentAccount.objects.create(phone="+77011112233", language="kk")
        self.consent()
        self.deliver(self.notify())
        self.assertEqual(mail.outbox[0].subject, "True Ballet: төлем туралы еске салу")

    def test_center_text_is_used(self):
        MessageTemplate.objects.create(
            organization=self.org, event="payment_due", channel="email", language="ru",
            subject="Оплата за {child}", body="Добрый день! Ждём оплату {amount}.",
        )  # fmt: skip
        self.consent()
        self.deliver(self.notify())
        self.assertEqual(mail.outbox[0].subject, "Оплата за Алия")
        self.assertTrue(mail.outbox[0].body.startswith("Добрый день! Ждём оплату 25 000 ₸."))

    def test_task_running_twice_sends_once(self):
        self.consent()
        message = self.notify()
        self.deliver(message)
        self.deliver(message)
        self.assertEqual(len(mail.outbox), 1)

    def test_quiet_hours_by_center_time(self):
        self.consent()
        late = datetime.datetime(2026, 10, 7, 23, 40, tzinfo=ALMATY)
        message = self.notify()
        with self.captureOnCommitCallbacks(execute=True):
            message = self.deliver(message, now=late)
        self.assertEqual(message.status, Status.DEFERRED)
        self.assertEqual(message.scheduled_for, datetime.datetime(2026, 10, 8, 9, 0, tzinfo=ALMATY))
        self.assertEqual(mail.outbox, [])
        self.later.assert_called_once()
        morning = datetime.datetime(2026, 10, 8, 9, 5, tzinfo=ALMATY)
        self.assertEqual(self.deliver(message, now=morning).status, Status.SENT)

    def test_no_channel_explains_why(self):
        self.parent.email = ""
        self.parent.save()
        self.consent()
        message = self.deliver(self.notify())
        self.assertEqual(message.status, Status.NO_CHANNEL)
        self.assertIn("нет email", message.error)
        self.assertIn("WhatsApp центру не подключён", message.error)

    def test_provider_failure_is_logged(self):
        self.consent()
        with mock.patch.object(EmailChannel, "send", side_effect=service.ChannelError("SMTP 550")):
            message = self.deliver(self.notify())
        self.assertEqual(message.status, Status.FAILED)
        self.assertEqual(message.error, "SMTP 550")


class UnsubscribeAndBounceTests(MessagingFixtures):
    def sent_message(self):
        self.consent()
        return self.deliver(self.notify())

    def test_link_page_does_not_unsubscribe_until_button(self):
        message = self.sent_message()
        url = f"/api/v1/messaging/unsubscribe/{service.unsubscribe_token(message)}/"
        page = APIClient().get(url)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(service.consent_status(self.parent, UTILITY), "opted_in")
        done = APIClient().post(url)
        self.assertEqual(done.status_code, 200)
        self.assertContains(done, "True Ballet")
        self.assertEqual(service.consent_status(self.parent, UTILITY), "opted_out")
        # Следующее сообщение уже не уходит.
        later = self.deliver(self.notify(key="payment_due:2"))
        self.assertEqual(later.status, Status.OPTED_OUT)

    def test_forged_link(self):
        response = APIClient().post("/api/v1/messaging/unsubscribe/abc/")
        self.assertEqual(response.status_code, 400)

    def test_bounce_and_complaint_from_provider(self):
        message = self.sent_message()
        OutboundMessage.objects.filter(pk=message.pk).update(provider_id="ses-1")
        service.on_email_event("ses-1", "bounced", "mailbox full")
        message.refresh_from_db()
        self.assertEqual(message.status, Status.FAILED)
        self.assertIn("mailbox full", message.error)
        service.on_email_event("ses-1", "complained")
        consent = MessagingConsent.objects.get(parent=self.parent, category=UTILITY)
        self.assertEqual((consent.status, consent.source), ("opted_out", "email_complaint"))


class MessagingApiTests(MessagingFixtures):
    def consent_url(self):
        return f"/api/v1/messaging/parents/{self.parent.id}/consent/"

    def test_admin_enables_utility_and_it_is_audited(self):
        admin = self.user("77010000003", User.Role.ADMIN)
        response = self.api(admin).put(self.consent_url(), {"utility": True}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["utility"]["status"], "opted_in")
        self.assertTrue(AuditLog.objects.filter(actor=admin, after__status="opted_in").exists())

    def test_staff_cannot_opt_parent_into_marketing(self):
        response = self.api().put(self.consent_url(), {"marketing": True}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_staff_cannot_undo_parents_own_unsubscribe(self):
        self.consent(MessagingConsent.Status.OPTED_OUT, source="unsubscribe_link")
        response = self.api().put(self.consent_url(), {"utility": True}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("только он", response.data["detail"])

    def test_template_with_unknown_placeholder_is_rejected(self):
        url = "/api/v1/messaging/templates/payment_due/ru/"
        bad = self.api().put(url, {"subject": "Оплата", "body": "{price}"}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertIn("{price}", bad.data["detail"])
        ok = self.api().put(url, {"subject": "Оплата {child}", "body": "{amount}"}, format="json")
        self.assertEqual(ok.status_code, 200)
        rows = {r["event"]: r for r in self.api().get("/api/v1/messaging/templates/").data}
        self.assertTrue(rows["payment_due"]["email"]["ru"]["customized"])
        self.api().delete(url)
        rows = {r["event"]: r for r in self.api().get("/api/v1/messaging/templates/").data}
        self.assertFalse(rows["payment_due"]["email"]["ru"]["customized"])

    def test_templates_and_settings_are_owner_only(self):
        admin = self.api(self.user("77010000004", User.Role.ADMIN))
        self.assertEqual(admin.get("/api/v1/messaging/templates/").status_code, 403)
        self.assertEqual(admin.get("/api/v1/messaging/settings/").status_code, 403)

    def test_settings_validate_and_save(self):
        url = "/api/v1/messaging/settings/"
        bad = self.api().put(url, {"quiet_from": 30, "quiet_to": 9, "channels": []}, format="json")
        self.assertEqual(bad.status_code, 400)
        payload = {"quiet_from": 22, "quiet_to": 8, "channels": ["email"], "reply_to": "hi@tb.kz"}
        data = self.api().put(url, payload, format="json").data
        self.assertEqual((data["quiet_from"], data["channels"]), (22, ["email"]))

    def test_journal_by_parent_and_isolated_between_centers(self):
        self.consent()
        self.deliver(self.notify())
        other = Organization.objects.create(name="Другой", slug="other-msg")
        stranger = ParentContact.objects.create(organization=other, full_name="Чужой")
        OutboundMessage.objects.create(
            organization=other, parent=stranger, event="payment_due",
            category=UTILITY, dedup_key="x",
        )  # fmt: skip
        data = self.api().get(f"/api/v1/messaging/messages/?parent={self.parent.id}").data
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["results"][0]["status"], "sent")
        self.assertEqual(self.api().get("/api/v1/messaging/messages/").data["total"], 1)


class ContractTests(TestCase):
    def test_nobody_sends_email_outside_messaging(self):
        """Правило из TRU-168: прямых вызовов провайдера вне центра рассылок нет."""
        root = pathlib.Path(__file__).resolve().parents[2]
        allowed = pathlib.Path(__file__).resolve().parent / "messaging"
        pattern = re.compile(r"\b(send_mail|send_mass_mail|EmailMessage|EmailMultiAlternatives)\(")
        offenders = [
            str(path.relative_to(root))
            for path in root.rglob("*.py")
            if allowed not in path.parents
            and "tests" not in path.name
            and pattern.search(path.read_text(encoding="utf-8"))
        ]
        self.assertEqual(offenders, [])
