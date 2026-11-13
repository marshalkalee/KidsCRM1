"""Опубликованное объявление уходит семьям: WhatsApp, push или email."""

from datetime import date, timedelta
from unittest import mock

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from domains.people.clients.models import Child, ChildContact, ParentContact
from domains.platform.notifications.messaging import service
from domains.platform.notifications.models import MessagingConsent, OutboundMessage
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group, GroupMembership

from .announcements import notify_parents
from .models import Announcement

TASK = "domains.people.portal.tasks.notify_announcement.delay"
DELIVER = "domains.platform.notifications.messaging.tasks.deliver_message.delay"


@override_settings(PUBLIC_BASE_URL="https://crm.example.kz")
class AnnouncementNotifyTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="announce-notify")
        self.owner = User.objects.create_user(
            phone="77009990051",
            password="password",
            full_name="Владелец",
            organization=self.org,
            role=User.Role.OWNER,
        )
        branch = Branch.objects.create(organization=self.org, name="Абая")
        ballet = Direction.objects.create(organization=self.org, name="Балет")
        self.group = Group.objects.create(
            organization=self.org, branch=branch, direction=ballet, name="Балет 6–8", capacity=12
        )
        self.other_group = Group.objects.create(
            organization=self.org, branch=branch, direction=ballet, name="Балет 9–12", capacity=12
        )
        self.mama = self.family("Исаева Мария", "Милана", self.group)
        self.other = self.family("Ахметова Айгуль", "Дана", self.other_group)
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def family(self, parent_name, child_name, group):
        parent = ParentContact.objects.create(organization=self.org, full_name=parent_name)
        child = Child.objects.create(
            organization=self.org, full_name=child_name, birth_date=date(2017, 1, 1)
        )
        ChildContact.objects.create(
            organization=self.org, child=child, parent_contact=parent, role=ChildContact.Role.MOTHER
        )
        GroupMembership.objects.create(
            organization=self.org, child=child, group=group, joined_at=date(2026, 9, 1)
        )
        service.set_consent(
            parent, "utility", MessagingConsent.Status.OPTED_IN, MessagingConsent.Source.ADMIN_FORM
        )
        return parent

    def announcement(self, **fields):
        values = {
            "title": "Отчётный концерт",
            "body": "Концерт 20 декабря в 18:00. Нужны белые купальники.",
            "status": Announcement.Status.PUBLISHED,
            **fields,
        }
        return Announcement.objects.create(organization=self.org, created_by=self.owner, **values)

    def notify(self, announcement):
        with mock.patch(DELIVER), self.captureOnCommitCallbacks(execute=True):
            return notify_parents(announcement)

    def test_publish_queues_notification_in_background(self):
        draft = self.announcement(status=Announcement.Status.DRAFT)
        with mock.patch(TASK) as delay, self.captureOnCommitCallbacks(execute=True):
            self.api.post(f"/api/v1/announcements/{draft.id}/publish/")
        delay.assert_called_once_with(str(draft.id))

    def test_only_families_of_the_audience_get_it(self):
        self.notify(self.announcement(audience=Announcement.Audience.GROUP, group=self.group))
        self.assertEqual(
            list(OutboundMessage.objects.values_list("parent", flat=True)), [self.mama.id]
        )

    def test_message_carries_the_announcement_text(self):
        announcement = self.announcement()
        self.notify(announcement)
        message = OutboundMessage.objects.get(parent=self.mama)
        self.assertEqual(message.event, "announcement")
        with mock.patch(
            "domains.platform.notifications.messaging.channels.EmailChannel.send", return_value=""
        ):
            self.mama.email = "maria@example.kz"
            self.mama.save()
            with mock.patch(
                "domains.platform.notifications.messaging.service.quiet_until", return_value=None
            ):
                message = service.deliver(message.id)
        self.assertIn("Нужны белые купальники", message.body)
        self.assertIn("https://crm.example.kz/parent/announcements", message.body)

    def test_republish_does_not_send_twice(self):
        announcement = self.announcement()
        self.notify(announcement)
        self.notify(announcement)
        self.assertEqual(OutboundMessage.objects.filter(parent=self.mama).count(), 1)

    def test_draft_and_expired_are_not_sent(self):
        self.assertEqual(self.notify(self.announcement(status=Announcement.Status.DRAFT)), 0)
        expired = self.announcement(expires_on=date.today() - timedelta(days=2))
        self.assertEqual(self.notify(expired), 0)
        self.assertFalse(OutboundMessage.objects.exists())
