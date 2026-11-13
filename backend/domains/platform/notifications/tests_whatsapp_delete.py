"""Удаление сообщений в чате WhatsApp: у себя и у всех."""

import datetime
from unittest import mock

from django.utils import timezone

from .messaging import service
from .messaging.whatsapp import handle_evolution_webhook
from .models import InboundWhatsAppMessage, OutboundMessage
from .tests_whatsapp_evolution import REQUEST, SLEEP, EvolutionBase

THREAD = "/api/v1/messaging/whatsapp/thread/"


class DeleteTests(EvolutionBase):
    def sent(self, text="Здравствуйте"):
        with mock.patch(
            "domains.platform.notifications.messaging.tasks.send_manual_whatsapp_task.delay"
        ):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.api.post(
                    "/api/v1/messaging/whatsapp/send/",
                    {"parent_id": str(self.parent.id), "text": text},
                    format="json",
                )
        with mock.patch(REQUEST, return_value={"key": {"id": "3EB0DEL"}}):
            with mock.patch(SLEEP):
                return service.deliver_manual(response.data["id"])

    def thread(self):
        return self.api.get(THREAD, {"parent": str(self.parent.id)}).data["results"]

    def delete(self, direction, message, for_everyone=False):
        return self.api.post(
            f"/api/v1/messaging/whatsapp/messages/{direction}/{message.id}/delete/",
            {"for_everyone": for_everyone},
            format="json",
        )

    def test_delete_for_me_hides_only_in_crm(self):
        self.number()
        message = self.sent()
        with mock.patch(REQUEST) as request:
            self.assertEqual(self.delete("out", message).status_code, 204)
        request.assert_not_called()
        self.assertEqual(self.thread(), [])
        # В журнале рассылок сообщение остаётся.
        self.assertTrue(OutboundMessage.objects.filter(pk=message.pk).exists())

    def test_delete_for_everyone_revokes_in_whatsapp(self):
        connection = self.number()
        message = self.sent()
        self.assertTrue(self.thread()[0]["can_revoke"])
        with mock.patch(REQUEST, return_value={}) as request:
            self.assertEqual(self.delete("out", message, for_everyone=True).status_code, 204)
        method, path, payload = request.call_args.args[:3]
        self.assertEqual(
            (method, path), ("DELETE", f"chat/deleteMessageForEveryone/{connection.instance_name}")
        )
        self.assertEqual(
            payload, {"id": "3EB0DEL", "fromMe": True, "remoteJid": "77001234567@s.whatsapp.net"}
        )
        row = self.thread()[0]
        self.assertTrue(row["revoked"])
        self.assertEqual(row["text"], "")
        self.assertFalse(row["can_revoke"])

    def test_old_message_cannot_be_deleted_for_everyone(self):
        self.number()
        message = self.sent()
        OutboundMessage.objects.filter(pk=message.pk).update(
            sent_at=timezone.now() - datetime.timedelta(days=3)
        )
        with mock.patch(REQUEST) as request:
            self.assertEqual(self.delete("out", message, for_everyone=True).status_code, 400)
        request.assert_not_called()

    def test_parent_message_only_for_me(self):
        connection = self.number()
        self.upsert(connection, text="Ой, не туда")
        message = InboundWhatsAppMessage.objects.get()
        self.assertEqual(self.delete("in", message, for_everyone=True).status_code, 400)
        self.assertEqual(self.delete("in", message).status_code, 204)
        self.assertEqual(self.thread(), [])

    def test_parent_deleted_own_message(self):
        connection = self.number()
        self.upsert(connection, text="Ой, не туда", message_id="WA-DEL")
        handle_evolution_webhook(
            connection.pk,
            {
                "event": "messages.delete",
                "data": {
                    "id": "WA-DEL",
                    "remoteJid": "77001234567@s.whatsapp.net",
                    "fromMe": False,
                },
            },
        )
        row = self.thread()[0]
        self.assertTrue(row["revoked"])
        self.assertEqual(row["text"], "")

    def test_teacher_cannot_delete(self):
        from domains.platform.users.models import User

        self.number()
        message = self.sent()
        teacher = User.objects.create_user(
            phone="77009990031",
            password="password",
            full_name="Преподаватель",
            organization=self.organization,
            role=User.Role.TEACHER,
        )
        self.api.force_authenticate(teacher)
        self.assertEqual(self.delete("out", message).status_code, 403)
