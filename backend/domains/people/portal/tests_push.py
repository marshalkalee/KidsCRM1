"""Push и уведомления в кабинете родителя (TRU-172)."""

import datetime
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from django.core import mail
from django.test import override_settings
from pywebpush import WebPushException

from domains.platform.notifications.messaging import service
from domains.platform.notifications.models import MessagingConsent, OutboundMessage

from .models import ParentAccount, PushSubscription
from .tests_auth import PortalAuthBase

NOON = datetime.datetime(2026, 10, 7, 12, 0, tzinfo=ZoneInfo("Asia/Almaty"))
SUBSCRIPTION = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/abc",
    "keys": {"p256dh": "BPk-key", "auth": "auth-secret"},
}
WEBPUSH = "pywebpush.webpush"


@override_settings(
    WEBPUSH_VAPID_PUBLIC_KEY="pub",
    WEBPUSH_VAPID_PRIVATE_KEY="priv",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class ParentPushTests(PortalAuthBase):
    def setUp(self):
        super().setUp()
        self.parent.email = "mama@example.kz"
        self.parent.save()
        self.client_parent = self.as_parent(self.login())
        mock.patch("domains.platform.notifications.messaging.tasks.deliver_message.delay").start()
        self.addCleanup(mock.patch.stopall)

    def subscribe(self, data=SUBSCRIPTION):
        return self.client_parent.post("/api/v1/portal/push/", data, format="json")

    def send(self, key="pay:1", event="payment_due"):
        message = service.notify(
            self.parent, event, {"child": "Айлин", "amount": "25 000 ₸"}, dedup_key=key
        )
        return service.deliver(message.id, now=NOON)

    def test_turning_on_reminders_is_consent_and_device_subscription(self):
        data = self.subscribe().data
        self.assertTrue(data["enabled"])
        self.assertTrue(data["this_device"])
        self.assertEqual(data["public_key"], "pub")
        consent = MessagingConsent.objects.get(parent=self.parent, category="utility")
        self.assertEqual((consent.status, consent.source), ("opted_in", "parent_portal"))

    def test_push_delivered_means_no_email_duplicate(self):
        self.subscribe()
        with mock.patch(WEBPUSH) as webpush:
            message = self.send()
        self.assertEqual((message.status, message.channel), ("sent", "push"))
        payload = webpush.call_args.kwargs["data"]
        self.assertIn("Напоминание об оплате", payload)
        self.assertIn("/parent/subscription", payload)
        # Подвал «отписаться» — только в письмах.
        self.assertNotIn("unsubscribe", message.body)
        self.assertEqual(mail.outbox, [])

    def test_dead_subscription_is_removed_and_email_takes_over(self):
        self.subscribe()
        gone = WebPushException("gone", response=SimpleNamespace(status_code=410))
        with mock.patch(WEBPUSH, side_effect=gone):
            message = self.send()
        self.assertFalse(PushSubscription.objects.exists())
        self.assertEqual((message.status, message.channel), ("sent", "email"))
        self.assertEqual(len(mail.outbox), 1)

    def test_parent_turns_off_one_type_for_all_channels(self):
        self.subscribe()
        self.client_parent.patch(
            "/api/v1/portal/notifications/", {"events": {"payment_due": False}}, format="json"
        )
        with mock.patch(WEBPUSH) as webpush:
            message = self.send()
        self.assertEqual(message.status, OutboundMessage.Status.OPTED_OUT)
        webpush.assert_not_called()
        self.assertEqual(mail.outbox, [])
        events = {
            e["key"]: e["enabled"]
            for e in self.client_parent.get("/api/v1/portal/notifications/").data["events"]
        }
        self.assertEqual((events["payment_due"], events["lesson_cancelled"]), (False, True))

    def test_turn_everything_off(self):
        self.subscribe()
        data = self.client_parent.patch(
            "/api/v1/portal/notifications/", {"enabled": False}, format="json"
        ).data
        self.assertFalse(data["enabled"])
        self.assertEqual(data["devices"], 0)
        self.assertEqual(self.send().status, OutboundMessage.Status.OPTED_OUT)

    def test_broken_subscription_is_rejected(self):
        response = self.subscribe({"endpoint": "http://x", "keys": {}})
        self.assertEqual(response.status_code, 400)

    def test_same_browser_under_another_number_moves_to_new_account(self):
        self.subscribe()
        other = ParentAccount.objects.create(phone="+77029998877")
        PushSubscription.objects.filter(endpoint=SUBSCRIPTION["endpoint"]).update(account=other)
        self.subscribe()
        self.assertEqual(PushSubscription.objects.get().account.phone, self.parent_phone())

    def parent_phone(self):
        return ParentAccount.objects.exclude(phone="+77029998877").get().phone

    @override_settings(WEBPUSH_VAPID_PUBLIC_KEY="", WEBPUSH_VAPID_PRIVATE_KEY="")
    def test_without_keys_push_is_skipped(self):
        self.subscribe()
        with mock.patch(WEBPUSH) as webpush:
            message = self.send()
        webpush.assert_not_called()
        self.assertEqual(message.channel, "email")
        self.assertIn("ключи VAPID", message.attempts[0]["reason"])
