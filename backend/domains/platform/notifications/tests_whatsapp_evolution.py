"""Номера WhatsApp по QR-коду через Evolution API: подключение по филиалам,
отправка, входящие, статусы доставки, отключение номера."""

import datetime
from datetime import date
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from domains.people.clients.models import Child, ChildContact, ContactPhone, ParentContact
from domains.platform.leads.models import Lead
from domains.platform.tasks.models import Task
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.tenants.org_settings import MESSAGING_CHANNELS
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group, GroupMembership

from .messaging import service
from .messaging.tasks import sync_evolution_states
from .messaging.whatsapp import connection_for, handle_evolution_webhook
from .models import (
    InboundWhatsAppMessage,
    MessageTemplate,
    MessagingConsent,
    OutboundMessage,
    WhatsAppConnection,
)

ALMATY = ZoneInfo("Asia/Almaty")
NOON = datetime.datetime(2026, 10, 7, 12, 0, tzinfo=ALMATY)
REQUEST = "domains.platform.notifications.messaging.evolution._request"
SLEEP = "domains.platform.notifications.messaging.evolution.time.sleep"
EVOLUTION = {
    "EVOLUTION_API_URL": "http://evolution:8080",
    "EVOLUTION_API_KEY": "secret-key",
    "PUBLIC_BASE_URL": "https://crm.example.kz",
    "EVOLUTION_WEBHOOK_BASE_URL": "",
}


@override_settings(**EVOLUTION)
class EvolutionBase(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="True Ballet", slug="evo-test")
        self.abaya = Branch.objects.create(organization=self.organization, name="Абая")
        self.orbita = Branch.objects.create(organization=self.organization, name="Орбита")
        self.parent = ParentContact.objects.create(
            organization=self.organization, full_name="Исаева Мария"
        )
        ContactPhone.objects.create(
            organization=self.organization, parent_contact=self.parent, number="+77001234567"
        )
        self.child = Child.objects.create(
            organization=self.organization,
            full_name="Милана Исаева",
            birth_date=datetime.date(2016, 4, 5),
        )
        ChildContact.objects.create(
            organization=self.organization,
            child=self.child,
            parent_contact=self.parent,
            role=ChildContact.Role.MOTHER,
            is_payer=True,
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

    def number(self, branch=None, **fields):
        defaults = {
            "mode": WhatsAppConnection.Mode.EVOLUTION,
            "status": WhatsAppConnection.Status.CONNECTED,
            "instance_name": f"kidscrm-{branch.pk.hex[:8] if branch else 'org'}",
            "webhook_secret": f"secret-{branch.pk.hex[:8] if branch else 'org'}",
            "business_phone": "+77070000000",
            "connected_at": timezone.now() - datetime.timedelta(days=1),
        }
        return WhatsAppConnection.objects.create(
            organization=self.organization, branch=branch, **{**defaults, **fields}
        )

    def join(self, branch):
        direction = Direction.objects.create(organization=self.organization, name="Балет")
        group = Group.objects.create(
            organization=self.organization,
            branch=branch,
            direction=direction,
            name="Балет 6–8",
            capacity=12,
        )
        GroupMembership.objects.create(
            organization=self.organization,
            child=self.child,
            group=group,
            joined_at=date(2026, 9, 1),
        )

    def notify(self, key="evo:1", event="payment_due", context=None):
        with mock.patch("domains.platform.notifications.messaging.tasks.deliver_message.delay"):
            with self.captureOnCommitCallbacks(execute=True):
                return service.notify(
                    self.parent,
                    event,
                    context or {"child": "Милана", "amount": "25 000 ₸", "_channel": "whatsapp"},
                    dedup_key=key,
                )

    def upsert(self, connection, *, jid="77001234567@s.whatsapp.net", text="Здравствуйте", **extra):
        key = {"remoteJid": jid, "fromMe": False, "id": extra.pop("message_id", "3EB0AA")}
        key.update(extra.pop("key", {}))
        data = {
            "key": key,
            "pushName": extra.pop("push_name", "Мария"),
            "message": extra.pop("message", {"conversation": text}),
            "messageType": "conversation",
            "messageTimestamp": int(extra.pop("timestamp", timezone.now()).timestamp()),
        }
        return handle_evolution_webhook(connection.pk, {"event": "messages.upsert", "data": data})


class RoutingTests(EvolutionBase):
    def test_parent_gets_number_of_childs_branch(self):
        org_number = self.number()
        orbita = self.number(self.orbita)
        self.assertEqual(connection_for(self.organization, self.parent), org_number)
        self.join(self.orbita)
        self.assertEqual(connection_for(self.organization, self.parent), orbita)

    def test_branch_without_number_falls_back_to_any_connected(self):
        abaya = self.number(self.abaya)
        self.join(self.orbita)
        self.assertEqual(connection_for(self.organization, self.parent), abaya)

    def test_disconnected_number_is_skipped(self):
        self.number(self.orbita, status=WhatsAppConnection.Status.DISCONNECTED)
        org_number = self.number()
        self.join(self.orbita)
        self.assertEqual(connection_for(self.organization, self.parent), org_number)


class SendingTests(EvolutionBase):
    def test_event_goes_as_plain_text(self):
        connection = self.number(self.abaya)
        self.join(self.abaya)
        with mock.patch(REQUEST, return_value={"key": {"id": "3EB0SENT"}}) as request:
            with mock.patch(SLEEP):
                message = service.deliver(self.notify().id, now=NOON)
        self.assertEqual(message.status, OutboundMessage.Status.SENT)
        self.assertEqual(message.provider_id, "3EB0SENT")
        self.assertNotIn("Стоп", message.body)
        method, path, payload = request.call_args.args[:3]
        self.assertEqual((method, path), ("POST", f"message/sendText/{connection.instance_name}"))
        self.assertEqual(payload["number"], "77001234567")
        self.assertIn("25 000 ₸", payload["text"])
        # Meta-шаблоны для номера по QR не нужны.
        self.assertFalse(MessageTemplate.objects.filter(channel="whatsapp").exists())

    def test_no_whatsapp_on_number_falls_back_to_next_channel(self):
        from .messaging.evolution import EvolutionError

        self.number()
        self.parent.email = "maria@example.kz"
        self.parent.save()
        message = self.notify(
            context={"child": "Милана", "amount": "25 000 ₸"},
        )
        self.organization.settings = {MESSAGING_CHANNELS: ["whatsapp", "email"]}
        self.organization.save()
        with mock.patch(REQUEST, side_effect=EvolutionError("У этого номера нет WhatsApp")):
            with mock.patch(SLEEP):
                message = service.deliver(message.id, now=NOON)
        self.assertEqual(message.channel, "email")
        self.assertEqual(message.status, OutboundMessage.Status.SENT)
        self.assertEqual(message.attempts[0]["error"], "У этого номера нет WhatsApp")

    def test_busy_number_requeues_message_instead_of_email(self):
        connection = self.number()
        connection.next_send_at = timezone.now() + datetime.timedelta(minutes=10)
        connection.save()
        message = self.notify()
        with (
            mock.patch(REQUEST) as request,
            mock.patch(
                "domains.platform.notifications.messaging.tasks.deliver_message.apply_async"
            ) as later,
        ):
            with self.captureOnCommitCallbacks(execute=True):
                message = service.deliver(message.id, now=NOON)
        request.assert_not_called()
        self.assertEqual(message.status, OutboundMessage.Status.QUEUED)
        self.assertIsNotNone(message.scheduled_for)
        later.assert_called_once()

    def test_reply_has_no_24_hour_window_and_uses_number_parent_wrote_to(self):
        self.number()
        abaya = self.number(self.abaya)
        with mock.patch(REQUEST):
            self.upsert(abaya, text="Можно перенести занятие?")
        response = self.api.get(f"/api/v1/messaging/messages/?parent={self.parent.id}")
        self.assertTrue(response.data["whatsapp_reply"]["available"])
        with mock.patch("domains.platform.notifications.messaging.tasks.deliver_message.delay"):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.api.post(
                    "/api/v1/messaging/whatsapp/reply/",
                    {"parent_id": str(self.parent.id), "body": "Да, напишите удобное время"},
                    format="json",
                )
        self.assertEqual(response.status_code, 202)
        with mock.patch(REQUEST, return_value={"key": {"id": "3EB0REPLY"}}) as request:
            with mock.patch(SLEEP):
                message = service.deliver(response.data["id"], now=NOON)
        self.assertEqual(message.status, OutboundMessage.Status.SENT)
        self.assertIn(abaya.instance_name, request.call_args.args[1])

    def test_bulk_is_ready_without_meta_templates(self):
        from domains.money.subscriptions.models import Subscription

        self.number()
        subscription = mock.Mock(
            spec=Subscription, id="sub-1", child_id=self.child.id, child=self.child
        )
        subscription.debt = 25000
        with mock.patch(
            "domains.platform.notifications.messaging.views._bulk_candidates",
            return_value=[(subscription, self.parent, "payment_due", {"child": "Милана"})],
        ):
            response = self.api.post(
                "/api/v1/messaging/whatsapp/bulk/",
                {"source": "debts", "ids": ["sub-1"]},
                format="json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["ready"], 1)
        self.assertEqual(response.data["results"][0]["mode"], "Обычный текст")
        self.assertEqual(response.data["results"][0]["number"], "Весь центр")


class InboundTests(EvolutionBase):
    def test_known_parent_message_goes_to_child_history(self):
        connection = self.number(self.abaya)
        self.upsert(connection)
        message = InboundWhatsAppMessage.objects.get()
        self.assertEqual(message.status, InboundWhatsAppMessage.Status.LINKED)
        self.assertEqual(message.child, self.child)
        self.assertEqual(message.connection, connection)
        self.assertEqual(message.sender_name, "Мария")

    def test_unknown_number_becomes_lead_of_that_branch(self):
        connection = self.number(self.orbita)
        self.upsert(connection, jid="77011112233@s.whatsapp.net", push_name="Айгерим")
        lead = Lead.objects.get()
        self.assertEqual(lead.phone, "+77011112233")
        self.assertEqual(lead.parent_name, "Айгерим")
        self.assertEqual(lead.branch, self.orbita)

    def test_own_messages_groups_and_history_are_ignored(self):
        connection = self.number()
        self.upsert(connection, key={"fromMe": True}, message_id="own")
        self.upsert(connection, jid="120363@g.us", message_id="group")
        self.upsert(connection, jid="status@broadcast", message_id="status")
        self.upsert(
            connection,
            message_id="history",
            timestamp=connection.connected_at - datetime.timedelta(days=3),
        )
        self.upsert(connection, message={"reactionMessage": {"text": "👍"}}, message_id="react")
        self.assertFalse(InboundWhatsAppMessage.objects.exists())

    def test_hidden_number_becomes_one_lead_for_all_messages(self):
        connection = self.number()
        self.upsert(connection, jid="1234567890@lid", push_name="Дана", message_id="lid-1")
        self.upsert(connection, jid="1234567890@lid", push_name="Дана", message_id="lid-2")
        lead = Lead.objects.get()
        self.assertEqual((lead.parent_name, lead.phone), ("Дана", ""))
        self.assertEqual(
            set(InboundWhatsAppMessage.objects.values_list("status", "lead_id")),
            {(InboundWhatsAppMessage.Status.LINKED, lead.id)},
        )

    def test_hidden_number_with_alt_jid_is_recognised(self):
        connection = self.number()
        self.upsert(
            connection,
            jid="1234567890@lid",
            key={"remoteJidAlt": "77001234567@s.whatsapp.net"},
        )
        self.assertEqual(InboundWhatsAppMessage.objects.get().child, self.child)

    def test_duplicate_event_is_stored_once(self):
        connection = self.number()
        self.upsert(connection)
        self.upsert(connection)
        self.assertEqual(InboundWhatsAppMessage.objects.count(), 1)

    def test_stop_word_is_just_a_chat_message(self):
        connection = self.number()
        self.upsert(connection, text="Стоп")
        self.assertEqual(
            service.consent_status(self.parent, "utility"), MessagingConsent.Status.OPTED_IN
        )
        self.assertEqual(InboundWhatsAppMessage.objects.get().text, "Стоп")

    def test_document_caption_is_kept(self):
        connection = self.number()
        self.upsert(
            connection,
            message={"documentMessage": {"fileName": "чек.pdf", "mimetype": "application/pdf"}},
        )
        message = InboundWhatsAppMessage.objects.get()
        self.assertEqual(message.message_type, "document")
        self.assertEqual(message.text, "чек.pdf")
        self.assertEqual(message.media["mime_type"], "application/pdf")


class StatusTests(EvolutionBase):
    def sent_message(self, connection):
        message = self.notify()
        message.status = OutboundMessage.Status.SENT
        message.provider_id = "3EB0SENT"
        message.save()
        return message

    def update(self, connection, status, key_id="3EB0SENT"):
        handle_evolution_webhook(
            connection.pk,
            {
                "event": "messages.update",
                "data": {"keyId": key_id, "fromMe": True, "status": status},
            },
        )

    def test_delivery_and_read_receipts_never_go_back(self):
        connection = self.number()
        message = self.sent_message(connection)
        self.update(connection, "READ")
        self.update(connection, "DELIVERY_ACK")
        message.refresh_from_db()
        self.assertEqual(message.status, OutboundMessage.Status.READ)

    def test_number_connected_by_qr_takes_phone_from_whatsapp(self):
        connection = self.number(
            status=WhatsAppConnection.Status.CONNECTING, business_phone="", connected_at=None
        )
        handle_evolution_webhook(
            connection.pk,
            {
                "event": "connection.update",
                "data": {"state": "open", "wuid": "77075554433@s.whatsapp.net"},
            },
        )
        connection.refresh_from_db()
        self.assertEqual(connection.status, WhatsAppConnection.Status.CONNECTED)
        self.assertEqual(connection.business_phone, "+77075554433")
        self.assertIsNotNone(connection.connected_at)

    def test_dropped_number_creates_task_for_owner_once(self):
        connection = self.number(self.abaya)
        payload = {"event": "connection.update", "data": {"state": "close"}}
        handle_evolution_webhook(connection.pk, payload)
        handle_evolution_webhook(connection.pk, payload)
        connection.refresh_from_db()
        self.assertEqual(connection.status, WhatsAppConnection.Status.DISCONNECTED)
        task = Task.objects.get()
        self.assertEqual(task.assigned_to, self.owner)
        self.assertEqual(task.branch, self.abaya)
        self.assertIn("Абая", task.title)

    def test_periodic_check_catches_lost_disconnect_event(self):
        connection = self.number()
        with mock.patch(REQUEST, return_value={"instance": {"state": "close"}}):
            sync_evolution_states()
        connection.refresh_from_db()
        self.assertEqual(connection.status, WhatsAppConnection.Status.DISCONNECTED)


class NumbersApiTests(EvolutionBase):
    URL = "/api/v1/messaging/whatsapp/numbers/"

    def test_connect_branch_number_returns_qr_and_registers_webhook(self):
        with mock.patch(
            REQUEST, return_value={"qrcode": {"base64": "data:image/png;base64,QR", "count": 1}}
        ) as request:
            response = self.api.post(self.URL, {"branch_id": str(self.abaya.id)}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["qr"]["base64"], "data:image/png;base64,QR")
        connection = WhatsAppConnection.objects.get()
        self.assertEqual(connection.branch, self.abaya)
        self.assertEqual(connection.status, WhatsAppConnection.Status.CONNECTING)
        payload = request.call_args.args[2]
        self.assertTrue(payload["groupsIgnore"])
        self.assertEqual(
            payload["webhook"]["url"],
            f"https://crm.example.kz/api/v1/messaging/whatsapp/evolution/{connection.webhook_secret}/",
        )
        listing = self.api.get(self.URL).data
        self.assertTrue(listing["available"])
        self.assertEqual([b["taken"] for b in listing["branches"]], [True, False])  # Абая, Орбита

    def test_polling_qr_marks_number_connected(self):
        connection = self.number(status=WhatsAppConnection.Status.CONNECTING, business_phone="")

        def fake(method, path, payload=None, timeout=None):
            if path.startswith("instance/connect/"):
                return {"instance": {"instanceName": connection.instance_name, "state": "open"}}
            return [{"name": connection.instance_name, "ownerJid": "77075554433@s.whatsapp.net"}]

        with mock.patch(REQUEST, side_effect=fake):
            response = self.api.get(f"{self.URL}{connection.id}/")
        self.assertEqual(response.data["number"]["status"], "connected")
        self.assertEqual(response.data["number"]["phone"], "+77075554433")
        self.assertIsNone(response.data["qr"])

    def test_disconnect_logs_out_and_removes_number(self):
        connection = self.number(self.abaya)
        with mock.patch(REQUEST, return_value={}) as request:
            response = self.api.delete(f"{self.URL}{connection.id}/")
        self.assertEqual(response.status_code, 204)
        paths = [call.args[1] for call in request.call_args_list]
        self.assertEqual(
            paths,
            [
                f"instance/logout/{connection.instance_name}",
                f"instance/delete/{connection.instance_name}",
            ],
        )
        self.assertFalse(WhatsAppConnection.objects.for_tenant(self.organization).exists())
        # Вебхук отключённого номера больше не принимается.
        response = self.api.post(
            f"/api/v1/messaging/whatsapp/evolution/{connection.webhook_secret}/",
            {"event": "messages.upsert", "data": {}},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    @override_settings(EVOLUTION_API_URL="")
    def test_not_configured_server_is_reported(self):
        response = self.api.post(self.URL, {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.api.get(self.URL).data["available"])

    def test_only_owner_manages_numbers(self):
        admin = User.objects.create_user(
            phone="77009990002",
            password="password",
            full_name="Админ",
            organization=self.organization,
            role=User.Role.ADMIN,
        )
        self.api.force_authenticate(admin)
        self.assertEqual(self.api.get(self.URL).status_code, 403)

    def test_meta_settings_do_not_overwrite_org_qr_number(self):
        self.number()
        response = self.api.put("/api/v1/messaging/whatsapp/", {"mode": "meta"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(WhatsAppConnection.objects.get().mode, WhatsAppConnection.Mode.EVOLUTION)

    def test_webhook_queues_event_for_number(self):
        connection = self.number()
        with mock.patch(
            "domains.platform.notifications.messaging.tasks.process_evolution_webhook.delay"
        ) as delay:
            response = APIClient().post(
                f"/api/v1/messaging/whatsapp/evolution/{connection.webhook_secret}/",
                {"event": "messages.upsert", "data": {"key": {"id": "1"}}, "apikey": "x"},
                format="json",
            )
        self.assertEqual(response.status_code, 200)
        delay.assert_called_once_with(
            str(connection.id), {"event": "messages.upsert", "data": {"key": {"id": "1"}}}
        )


class ManualSendTests(EvolutionBase):
    """Кнопка «WhatsApp» в карточках, задачах и списках — с номера центра."""

    URL = "/api/v1/messaging/whatsapp/send/"
    TASK = "domains.platform.notifications.messaging.tasks.send_manual_whatsapp_task.delay"

    def send(self, **data):
        with mock.patch(self.TASK) as delay:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.api.post(self.URL, data, format="json")
        return response, delay

    def deliver(self, message_id, provider_id="3EB0MANUAL"):
        with mock.patch(REQUEST, return_value={"key": {"id": provider_id}}) as request:
            with mock.patch(SLEEP):
                message = service.deliver_manual(message_id)
        return message, request

    def test_message_to_new_lead_goes_from_center_number_and_into_lead_history(self):
        from domains.platform.leads.models import LeadComment

        self.number(self.orbita)
        lead = Lead.objects.create(
            organization=self.organization, parent_name="Айгерим", phone="+77011112233"
        )
        response, delay = self.send(
            lead_id=str(lead.id), text="Здравствуйте! Когда удобно на пробное?"
        )
        self.assertEqual(response.status_code, 202)
        self.assertNotIn("recipient", response.data)
        delay.assert_called_once_with(response.data["id"])
        message, request = self.deliver(response.data["id"])
        self.assertEqual(message.status, OutboundMessage.Status.SENT)
        self.assertEqual(message.lead, lead)
        self.assertIsNone(message.parent)
        self.assertEqual(request.call_args.args[2]["number"], "77011112233")
        self.assertFalse(LeadComment.objects.filter(lead=lead).exists())
        journal = self.api.get("/api/v1/messaging/messages/").data["results"][0]
        self.assertIsNone(journal["parent"])
        self.assertEqual(journal["lead"]["name"], "Айгерим")
        self.assertEqual(journal["event_label"], "Сообщение в WhatsApp")

    def test_phone_from_list_finds_parent_and_logs_to_child_card(self):
        from domains.people.clients.models import CommunicationLog

        self.number()
        response, _ = self.send(
            phone="+7 700 123 45 67", child_id=str(self.child.id), text="Напоминаем об оплате"
        )
        self.assertEqual(response.status_code, 202)
        message = OutboundMessage.objects.get(pk=response.data["id"])
        self.assertEqual(message.parent, self.parent)
        self.assertTrue(
            CommunicationLog.objects.filter(child=self.child, note__contains="Напоминаем").exists()
        )

    def test_manual_message_goes_regardless_of_mailing_consent(self):
        self.number()
        service.set_consent(
            self.parent,
            "utility",
            MessagingConsent.Status.OPTED_OUT,
            MessagingConsent.Source.WHATSAPP_REPLY,
        )
        response, delay = self.send(parent_id=str(self.parent.id), text="Здравствуйте")
        self.assertEqual(response.status_code, 202)
        delay.assert_called_once()

    def test_unknown_number_is_rejected(self):
        self.number()
        response, _ = self.send(phone="+77779998877", text="Привет")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(OutboundMessage.objects.exists())

    def test_meta_only_center_keeps_personal_whatsapp_buttons(self):
        WhatsAppConnection.objects.create(
            organization=self.organization,
            mode=WhatsAppConnection.Mode.META,
            status=WhatsAppConnection.Status.CONNECTED,
        )
        status = self.api.get("/api/v1/messaging/whatsapp/status/").data
        self.assertEqual(status, {"connected": False, "can_send": False})
        response, _ = self.send(parent_id=str(self.parent.id), text="Здравствуйте")
        self.assertEqual(response.status_code, 400)

    def test_teacher_sees_status_but_cannot_send(self):
        self.number()
        teacher = User.objects.create_user(
            phone="77009990003",
            password="password",
            full_name="Преподаватель",
            organization=self.organization,
            role=User.Role.TEACHER,
        )
        self.api.force_authenticate(teacher)
        self.assertEqual(
            self.api.get("/api/v1/messaging/whatsapp/status/").data,
            {"connected": True, "can_send": False},
        )
        response, _ = self.send(parent_id=str(self.parent.id), text="Здравствуйте")
        self.assertEqual(response.status_code, 403)

    def test_reply_to_lead_closes_unanswered_task(self):
        from .messaging.tasks import create_unanswered_whatsapp_tasks

        connection = self.number()
        self.upsert(connection, jid="77011112233@s.whatsapp.net", push_name="Айгерим")
        lead = Lead.objects.get()
        InboundWhatsAppMessage.objects.update(
            created_at=timezone.now() - datetime.timedelta(hours=6)
        )
        self.send(lead_id=str(lead.id), text="Здравствуйте, Айгерим!")
        create_unanswered_whatsapp_tasks()
        self.assertFalse(Task.objects.filter(type=Task.Type.CALL_BACK).exists())

    def test_disconnected_number_fails_message_without_crash(self):
        connection = self.number()
        response, _ = self.send(parent_id=str(self.parent.id), text="Здравствуйте")
        connection.status = WhatsAppConnection.Status.DISCONNECTED
        connection.save()
        message = service.deliver_manual(response.data["id"])
        self.assertEqual(message.status, OutboundMessage.Status.FAILED)


class CommunicationsFeedTests(EvolutionBase):
    """Переписка WhatsApp — в ленте «Коммуникации» карточки родителя."""

    FEED = "/api/v1/clients/communications/"

    def feed(self):
        data = self.api.get(self.FEED, {"family": str(self.parent.id)}).data
        return data["results"] if isinstance(data, dict) else data

    def test_parent_without_children_sees_both_directions(self):
        ChildContact.objects.all().delete()
        connection = self.number()
        self.upsert(connection, text="не хочу", message_id="in-1")
        self.assertEqual(InboundWhatsAppMessage.objects.get().status, "linked")
        with mock.patch(
            "domains.platform.notifications.messaging.tasks.send_manual_whatsapp_task.delay"
        ):
            with self.captureOnCommitCallbacks(execute=True):
                self.api.post(
                    "/api/v1/messaging/whatsapp/send/",
                    {"parent_id": str(self.parent.id), "text": "Почему?"},
                    format="json",
                )
        rows = self.feed()
        self.assertEqual(
            [(r["note"], r["incoming"], r["author_name"]) for r in rows],
            [("Почему?", False, "Владелец"), ("не хочу", True, None)],
        )
        self.assertTrue(all(r["channel"] == "whatsapp" and r["child"] is None for r in rows))

    def test_message_from_parent_with_one_child_goes_to_child(self):
        connection = self.number()
        self.upsert(connection, text="Заболели")
        rows = self.feed()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["child_name"], "Милана Исаева")
        self.assertTrue(rows[0]["incoming"])

    def test_parent_with_several_children_gets_message_without_manual_choice(self):
        second = Child.objects.create(
            organization=self.organization, full_name="Алия Исаева", birth_date=date(2018, 1, 1)
        )
        ChildContact.objects.create(
            organization=self.organization,
            child=second,
            parent_contact=self.parent,
            role=ChildContact.Role.MOTHER,
        )
        connection = self.number()
        self.upsert(connection, text="Кто из детей?")
        message = InboundWhatsAppMessage.objects.get()
        self.assertEqual(message.status, "linked")
        rows = self.feed()
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["child_name"])

    def test_manual_log_about_parent_without_child(self):
        ChildContact.objects.all().delete()
        response = self.api.post(
            self.FEED,
            {
                "parent_contact": str(self.parent.id),
                "channel": "call",
                "note": "Перезвонить в пятницу",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.feed()[0]["note"], "Перезвонить в пятницу")
        response = self.api.post(self.FEED, {"channel": "call", "note": "Ни о ком"}, format="json")
        self.assertEqual(response.status_code, 400)


class ThreadTests(EvolutionBase):
    """Чат WhatsApp в карточке родителя и заявки."""

    URL = "/api/v1/messaging/whatsapp/thread/"

    def test_parent_chat_has_both_directions_in_order(self):
        ChildContact.objects.all().delete()
        connection = self.number()
        self.upsert(connection, text="не хочу", message_id="in-1")
        with mock.patch(
            "domains.platform.notifications.messaging.tasks.send_manual_whatsapp_task.delay"
        ):
            with self.captureOnCommitCallbacks(execute=True):
                self.api.post(
                    "/api/v1/messaging/whatsapp/send/",
                    {"parent_id": str(self.parent.id), "text": "Почему?"},
                    format="json",
                )
        rows = self.api.get(self.URL, {"parent": str(self.parent.id)}).data["results"]
        self.assertEqual(
            [(r["direction"], r["text"]) for r in rows], [("in", "не хочу"), ("out", "Почему?")]
        )
        self.assertEqual(rows[1]["author"], "Владелец")

    def test_lead_chat_by_phone(self):
        connection = self.number()
        self.upsert(connection, jid="77011112233@s.whatsapp.net", text="Сколько стоит?")
        lead = Lead.objects.get()
        rows = self.api.get(self.URL, {"lead": str(lead.id)}).data["results"]
        self.assertEqual([(r["direction"], r["text"]) for r in rows], [("in", "Сколько стоит?")])

    def test_notes_block_skips_whatsapp(self):
        connection = self.number()
        self.upsert(connection, text="Здравствуйте")
        data = self.api.get(
            "/api/v1/clients/communications/",
            {"family": str(self.parent.id), "exclude_channel": "whatsapp"},
        ).data
        rows = data["results"] if isinstance(data, dict) else data
        self.assertEqual(rows, [])


class BellTests(EvolutionBase):
    """Колокольчик: пришло сообщение в WhatsApp — видно сразу."""

    def bell(self, user=None):
        if user:
            self.api.force_authenticate(user)
        items = self.api.get("/api/v1/notifications/").data
        items = items.get("items", items) if isinstance(items, dict) else items
        return next((item for item in items if item["kind"] == "whatsapp_messages"), None)

    def test_new_message_shows_who_wrote_and_opens_card(self):
        connection = self.number()
        self.upsert(connection, text="Можно перенести?")
        item = self.bell()
        self.assertEqual(item["count"], 1)
        self.assertTrue(item["unread"])
        self.assertEqual(item["name"], "Исаева Мария")
        self.assertEqual(item["preview"], "Можно перенести?")
        self.assertEqual(item["link"], f"/parents/{self.parent.id}")

    def test_reply_from_center_clears_it(self):
        connection = self.number()
        self.upsert(connection, text="Можно перенести?")
        with mock.patch(
            "domains.platform.notifications.messaging.tasks.send_manual_whatsapp_task.delay"
        ):
            with self.captureOnCommitCallbacks(execute=True):
                self.api.post(
                    "/api/v1/messaging/whatsapp/send/",
                    {"parent_id": str(self.parent.id), "text": "Да"},
                    format="json",
                )
        self.assertEqual(self.bell()["count"], 0)

    def test_two_conversations_counted_and_newest_first(self):
        connection = self.number()
        self.upsert(connection, text="Мама", message_id="m-1")
        self.upsert(
            connection, jid="77011112233@s.whatsapp.net", push_name="Айгерим", message_id="m-2"
        )
        item = self.bell()
        self.assertEqual(item["count"], 2)
        self.assertEqual(item["name"], "Айгерим")

    def test_hidden_for_teachers_and_centers_without_whatsapp(self):
        self.assertIsNone(self.bell())
        self.number()
        teacher = User.objects.create_user(
            phone="77009990004",
            password="password",
            full_name="Преподаватель",
            organization=self.organization,
            role=User.Role.TEACHER,
        )
        self.assertIsNone(self.bell(teacher))
