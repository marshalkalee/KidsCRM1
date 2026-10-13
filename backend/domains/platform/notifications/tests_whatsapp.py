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

from domains.people.clients.models import (
    Child,
    ChildContact,
    CommunicationLog,
    ContactPhone,
    ParentContact,
)
from domains.platform.leads.models import Lead, LeadComment
from domains.platform.tasks.models import Task
from domains.platform.tenants.models import Organization
from domains.platform.users.models import User

from .messaging import service
from .messaging.tasks import create_unanswered_whatsapp_tasks
from .messaging.whatsapp import (
    ensure_default_templates,
    handle_webhook,
    valid_webhook_signature,
    within_service_window,
)
from .models import (
    InboundWhatsAppMessage,
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

    def incoming(self, phone="77001234567", text="Здравствуйте", message_id="wamid.1"):
        return {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": "console-phone"},
                                "messages": [
                                    {
                                        "id": message_id,
                                        "from": phone,
                                        "type": "text",
                                        "text": {"body": text},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }

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

    def test_known_parent_message_is_added_to_child_communications_once(self):
        child = Child.objects.create(
            organization=self.organization,
            full_name="Милана Исаева",
            birth_date=datetime.date(2016, 4, 5),
        )
        ChildContact.objects.create(
            organization=self.organization,
            child=child,
            parent_contact=self.parent,
            role=ChildContact.Role.MOTHER,
        )
        payload = self.incoming()
        handle_webhook(payload)
        handle_webhook(payload)
        inbound = InboundWhatsAppMessage.objects.get(provider_message_id="wamid.1")
        self.assertEqual(inbound.status, InboundWhatsAppMessage.Status.LINKED)
        self.assertEqual(inbound.child, child)
        self.assertEqual(CommunicationLog.objects.filter(child=child).count(), 1)

    def test_unknown_phone_creates_new_whatsapp_lead_and_comment(self):
        handle_webhook(self.incoming("77007778899", "Хочу на балет", "wamid.new"))
        lead = Lead.objects.get(phone="+77007778899")
        self.assertEqual(lead.status, Lead.Status.NEW)
        self.assertEqual(lead.source.name, "WhatsApp")
        self.assertIn("Хочу на балет", LeadComment.objects.get(lead=lead).text)

    def test_multiple_children_wait_for_manual_choice(self):
        children = []
        for index in range(2):
            child = Child.objects.create(
                organization=self.organization,
                full_name=f"Ребёнок {index}",
                birth_date=datetime.date(2015, 1, index + 1),
            )
            ChildContact.objects.create(
                organization=self.organization,
                child=child,
                parent_contact=self.parent,
                role=ChildContact.Role.MOTHER,
            )
            children.append(child)
        handle_webhook(self.incoming(message_id="wamid.ambiguous"))
        message = InboundWhatsAppMessage.objects.get(provider_message_id="wamid.ambiguous")
        self.assertEqual(message.status, InboundWhatsAppMessage.Status.UNRESOLVED)
        response = self.api.post(
            f"/api/v1/messaging/whatsapp/inbox/{message.id}/resolve/",
            {"child_id": str(children[1].id)},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        message.refresh_from_db()
        self.assertEqual(message.child, children[1])
        self.assertEqual(message.status, InboundWhatsAppMessage.Status.LINKED)

    def test_webhook_api_queues_processing(self):
        with mock.patch(
            "domains.platform.notifications.messaging.tasks.process_whatsapp_webhook.delay"
        ) as delay:
            response = self.api.post(
                "/api/v1/messaging/whatsapp/webhook/",
                self.incoming(message_id="wamid.queued"),
                format="json",
            )
        self.assertEqual(response.status_code, 200)
        delay.assert_called_once()

    def test_unanswered_inbound_creates_one_callback_task(self):
        lead = Lead.objects.create(
            organization=self.organization,
            parent_name="Новый родитель",
            phone="+77007770000",
            assigned_to=self.owner,
        )
        message = InboundWhatsAppMessage.objects.create(
            organization=self.organization,
            provider_message_id="wamid.unanswered",
            sender_phone=lead.phone,
            text="Когда можно прийти?",
            lead=lead,
            status=InboundWhatsAppMessage.Status.LINKED,
        )
        InboundWhatsAppMessage.objects.filter(pk=message.pk).update(
            created_at=timezone.now() - datetime.timedelta(hours=5)
        )
        create_unanswered_whatsapp_tasks()
        create_unanswered_whatsapp_tasks()
        task = Task.objects.get(source_key=f"whatsapp-inbound:{message.id}")
        self.assertEqual(task.assigned_to, self.owner)
        self.assertEqual(Task.objects.filter(source_key=task.source_key).count(), 1)

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
