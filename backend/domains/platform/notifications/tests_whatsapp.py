import datetime
import hashlib
import hmac
import uuid
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from domains.people.clients.models import ContactPhone, ParentContact
from domains.platform.tenants.models import Organization
from domains.platform.users.models import User

from .messaging import service
from .messaging.whatsapp import (
    ensure_default_templates,
    handle_webhook,
    valid_webhook_signature,
    within_service_window,
)
from .models import (
    MessageTemplate,
    MessagingConsent,
    OutboundMessage,
    WhatsAppConnection,
    WhatsAppContactWindow,
)

ALMATY = ZoneInfo("Asia/Almaty")
NOON = datetime.datetime(2026, 10, 7, 12, 0, tzinfo=ALMATY)


class WhatsAppMessagingTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="True Ballet", slug="wa-test")
        self.parent = ParentContact.objects.create(
            organization=self.organization,
            full_name="Исаева Мария",
        )
        ContactPhone.objects.create(
            organization=self.organization,
            parent_contact=self.parent,
            number="+77001234567",
        )
        self.connection = WhatsAppConnection.objects.create(
            organization=self.organization,
            mode=WhatsAppConnection.Mode.CONSOLE,
            status=WhatsAppConnection.Status.CONNECTED,
            phone_number_id="console-phone",
        )
        service.set_consent(
            self.parent,
            "utility",
            MessagingConsent.Status.OPTED_IN,
            MessagingConsent.Source.ADMIN_FORM,
        )
        self.owner = User.objects.create_user(
            phone="77009990001",
            password="password",
            full_name="Владелец",
            organization=self.organization,
            role=User.Role.OWNER,
        )
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def notify(self, key="wa:1"):
        with mock.patch("domains.platform.notifications.messaging.tasks.deliver_message.delay"):
            with self.captureOnCommitCallbacks(execute=True):
                return service.notify(
                    self.parent,
                    "payment_due",
                    {"child": "Милана", "amount": "25 000 ₸", "_channel": "whatsapp"},
                    dedup_key=key,
                )

    def test_console_sync_approves_templates_and_sends(self):
        ensure_default_templates(self.connection)
        message = service.deliver(self.notify().id, now=NOON)
        self.assertEqual(message.status, OutboundMessage.Status.SENT)
        self.assertEqual(message.channel, "whatsapp")
        self.assertEqual(message.recipient, "+77001234567")
        self.assertTrue(message.provider_id.startswith("console-wa-"))

    def test_unapproved_template_never_reaches_provider(self):
        ensure_default_templates(self.connection)
        MessageTemplate.objects.filter(
            organization=self.organization,
            event="payment_due",
            channel="whatsapp",
            language="ru",
        ).update(provider_status=MessageTemplate.ProviderStatus.PENDING)
        message = service.deliver(self.notify("wa:pending").id, now=NOON)
        self.assertEqual(message.status, OutboundMessage.Status.FAILED)
        self.assertIn("не одобрен", message.error)

    def test_webhook_updates_receipts_and_opens_window(self):
        ensure_default_templates(self.connection)
        message = service.deliver(self.notify("wa:webhook").id, now=NOON)
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": "console-phone"},
                                "statuses": [{"id": message.provider_id, "status": "read"}],
                                "messages": [{"from": "77001234567", "text": {"body": "Спасибо"}}],
                            }
                        }
                    ]
                }
            ]
        }
        handle_webhook(payload)
        message.refresh_from_db()
        self.assertEqual(message.status, OutboundMessage.Status.READ)
        self.assertTrue(within_service_window(self.parent))

    def test_stop_reply_opts_out_of_both_categories(self):
        handle_webhook(
            {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "metadata": {"phone_number_id": "console-phone"},
                                    "messages": [{"from": "77001234567", "text": {"body": "СТОП"}}],
                                }
                            }
                        ]
                    }
                ]
            }
        )
        statuses = set(
            MessagingConsent.objects.filter(parent=self.parent).values_list("category", "status")
        )
        self.assertEqual(
            statuses,
            {("utility", "opted_out"), ("marketing", "opted_out")},
        )

    def test_free_text_reply_is_sent_only_inside_service_window(self):
        WhatsAppContactWindow.objects.create(
            organization=self.organization,
            parent=self.parent,
            last_inbound_at=timezone.now(),
        )
        with mock.patch("domains.platform.notifications.messaging.tasks.deliver_message.delay"):
            with self.captureOnCommitCallbacks(execute=True):
                message = service.notify_whatsapp_reply(self.parent, "Здравствуйте!")
        message = service.deliver(message.id, now=NOON)
        self.assertEqual(message.status, OutboundMessage.Status.SENT)
        self.assertEqual(message.body, "Здравствуйте!")
        self.assertTrue(message.provider_id.startswith("console-wa-reply-"))

    def test_reply_api_rejects_free_text_after_24_hours(self):
        WhatsAppContactWindow.objects.create(
            organization=self.organization,
            parent=self.parent,
            last_inbound_at=timezone.now() - datetime.timedelta(hours=25),
        )
        response = self.api.post(
            "/api/v1/messaging/whatsapp/reply/",
            {"parent_id": str(self.parent.id), "body": "Здравствуйте!"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("24-часовое", response.data["detail"])

    @override_settings(WHATSAPP_APP_SECRET="test-secret")
    def test_webhook_signature_is_checked(self):
        body = b'{"object":"whatsapp_business_account"}'
        digest = hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
        self.assertTrue(valid_webhook_signature(body, f"sha256={digest}"))
        self.assertFalse(valid_webhook_signature(body, "sha256=wrong"))

    def test_bulk_preview_shows_template_and_skipped_number_is_journalled(self):
        ensure_default_templates(self.connection)
        subscription = SimpleNamespace(
            id=uuid.uuid4(),
            child=SimpleNamespace(full_name="Милана Исаева"),
        )
        candidate = (subscription, self.parent, "subscription_ending", {"child": "Милана"})
        with mock.patch(
            "domains.platform.notifications.messaging.views._bulk_candidates",
            return_value=[candidate],
        ):
            preview = self.api.post(
                "/api/v1/messaging/whatsapp/bulk/",
                {"source": "renewals", "ids": [str(subscription.id)], "preview": True},
                format="json",
            )
            self.assertEqual(preview.status_code, 200)
            self.assertEqual(preview.data["templates"][0]["name"], "kidscrm_subscription_ending_ru")

            ContactPhone.objects.filter(parent_contact=self.parent).delete()
            sent = self.api.post(
                "/api/v1/messaging/whatsapp/bulk/",
                {"source": "renewals", "ids": [str(subscription.id)], "preview": False},
                format="json",
            )
        self.assertEqual(sent.status_code, 200)
        message = OutboundMessage.objects.get(parent=self.parent)
        self.assertEqual(message.status, OutboundMessage.Status.NO_CHANNEL)
        self.assertEqual(message.error, "Нет номера WhatsApp")
