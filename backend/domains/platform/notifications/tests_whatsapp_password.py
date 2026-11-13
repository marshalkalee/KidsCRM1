"""Пароль от кабинета — с номера центра, обычным сообщением в чате."""

from unittest import mock

from .messaging import service
from .models import OutboundMessage
from .tests_whatsapp_evolution import REQUEST, SLEEP, EvolutionBase

TASK = "domains.platform.notifications.messaging.tasks.send_manual_whatsapp_task.delay"


class PortalPasswordTests(EvolutionBase):
    def issue(self):
        response = self.api.post(f"/api/v1/clients/parents/{self.parent.id}/portal-access/")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["password"]

    def send(self, password):
        with mock.patch(TASK) as delay, self.captureOnCommitCallbacks(execute=True):
            response = self.api.post(
                f"/api/v1/clients/parents/{self.parent.id}/portal-access/send/",
                {"password": password},
                format="json",
            )
        return response, delay

    def test_password_goes_from_center_number_and_is_seen_in_chat(self):
        self.number()
        password = self.issue()
        response, delay = self.send(password)
        self.assertEqual(response.status_code, 202)
        with mock.patch(REQUEST, return_value={"key": {"id": "3EB0PWD"}}) as request:
            with mock.patch(SLEEP):
                sent = service.deliver_manual(delay.call_args.args[0])
        self.assertEqual(sent.status, OutboundMessage.Status.SENT)
        self.assertIn(password, request.call_args.args[2]["text"])
        rows = self.api.get(
            "/api/v1/messaging/whatsapp/thread/", {"parent": str(self.parent.id)}
        ).data["results"]
        self.assertIn(f"пароль: {password}", rows[0]["text"])

    def test_wrong_password_is_not_sent(self):
        self.number()
        self.issue()
        response, delay = self.send("not-the-password")
        self.assertEqual(response.status_code, 400)
        delay.assert_not_called()
        self.assertFalse(OutboundMessage.objects.exists())
