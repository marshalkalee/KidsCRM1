import base64
import datetime
import hashlib
import hmac
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from domains.people.clients.models import (
    Child,
    ChildContact,
    CommunicationLog,
    ContactPhone,
    ParentContact,
)
from domains.platform.core.audit import AuditLog
from domains.platform.leads.models import Lead
from domains.platform.tasks.models import Task
from domains.platform.tenants.models import Organization
from domains.platform.users.models import User

from .messaging.telephony import record_event, valid_zadarma_webhook_signature
from .models import CallRecord, TelephonyConnection


class TelephonyTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="telephony-test")
        self.owner = User.objects.create_user(
            phone="77010000001",
            password="p",
            full_name="Владелец",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.parent = ParentContact.objects.create(
            organization=self.org,
            full_name="Исаева Мария",
        )
        ContactPhone.objects.create(
            organization=self.org,
            parent_contact=self.parent,
            number="+77011112233",
        )
        self.child = Child.objects.create(
            organization=self.org,
            full_name="Исаева Милана",
            birth_date=datetime.date(2016, 1, 1),
        )
        ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=self.parent,
            role=ChildContact.Role.MOTHER,
            is_primary_contact=True,
        )
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def event(self, call_id="call-1", phone="+77011112233", status="completed", **extra):
        return {
            "call_id": call_id,
            "phone": phone,
            "direction": "inbound",
            "status": status,
            "started_at": timezone.now(),
            "duration_seconds": 42,
            **extra,
        }

    def test_known_number_links_client_and_writes_communication(self):
        call = record_event(self.org, self.event())
        self.assertEqual(call.parent, self.parent)
        self.assertEqual(call.child, self.child)
        self.assertEqual(CommunicationLog.objects.get().channel, CommunicationLog.Channel.CALL)

    def test_shared_parent_phone_does_not_open_an_arbitrary_child(self):
        second_child = Child.objects.create(
            organization=self.org,
            full_name="Исаева София",
            birth_date=datetime.date(2018, 1, 1),
        )
        ChildContact.objects.create(
            organization=self.org,
            child=second_child,
            parent_contact=self.parent,
            role=ChildContact.Role.MOTHER,
        )
        call = record_event(self.org, self.event("family-call"))
        self.assertEqual(call.parent, self.parent)
        self.assertIsNone(call.child)

    def test_later_event_keeps_recording_and_employee(self):
        call = record_event(
            self.org,
            self.event(
                employee_id=str(self.owner.id),
                recording_url="https://pbx.example/recording/kept",
            ),
        )
        updated = record_event(
            self.org,
            {
                "call_id": call.provider_call_id,
                "phone": call.phone,
                "status": "completed",
            },
        )
        self.assertEqual(updated.employee, self.owner)
        self.assertEqual(updated.recording_url, "https://pbx.example/recording/kept")

    def test_missed_number_creates_one_open_callback_task(self):
        record_event(self.org, self.event("missed-1", status="missed"))
        with patch("domains.platform.notifications.messaging.telephony.create_task") as create:
            record_event(self.org, self.event("missed-2", status="missed"))
        create.assert_not_called()
        tasks = Task.objects.filter(type=Task.Type.CALL_BACK, status=Task.Status.OPEN)
        self.assertEqual(tasks.count(), 1)
        self.assertEqual(tasks.get().child, self.child)

    def test_unknown_number_is_promoted_to_lead_only_by_employee(self):
        call = record_event(self.org, self.event("unknown-1", "+77019998877", "ringing"))
        self.assertIsNone(call.lead_id)
        response = self.api.post(f"/api/v1/messaging/telephony/calls/{call.id}/promote/")
        self.assertEqual(response.status_code, 200)
        lead = Lead.objects.get(pk=response.data["lead_id"])
        self.assertEqual(lead.phone, "+77019998877")
        self.assertEqual(lead.source.name, "Звонок")

    def test_recording_access_is_role_limited_and_audited(self):
        call = record_event(
            self.org,
            self.event("recorded-1", recording_url="https://pbx.example/recording/1"),
        )
        TelephonyConnection.objects.create(
            organization=self.org,
            recording_enabled=True,
            recording_notice_confirmed=True,
            recording_roles=[User.Role.OWNER],
        )
        response = self.api.get(f"/api/v1/messaging/telephony/calls/{call.id}/recording/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            AuditLog.objects.get().action,
            AuditLog.Action.PLAY_CALL_RECORDING,
        )
        teacher = User.objects.create_user(
            phone="77010000002",
            password="p",
            full_name="Преподаватель",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        self.api.force_authenticate(teacher)
        denied = self.api.get(f"/api/v1/messaging/telephony/calls/{call.id}/recording/")
        self.assertEqual(denied.status_code, 403)

    def test_other_organization_cannot_read_call(self):
        call = record_event(self.org, self.event())
        other_org = Organization.objects.create(name="Other", slug="other-telephony")
        other_owner = User.objects.create_user(
            phone="77010000003",
            password="p",
            full_name="Другой",
            organization=other_org,
            role=User.Role.OWNER,
        )
        self.api.force_authenticate(other_owner)
        response = self.api.post(f"/api/v1/messaging/telephony/calls/{call.id}/seen/")
        self.assertEqual(response.status_code, 404)

    def test_console_outgoing_degrades_to_tel_link(self):
        response = self.api.post(
            "/api/v1/messaging/telephony/outgoing/",
            {"phone": "+77011112233"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["started"])
        self.assertEqual(response.data["tel_url"], "tel:+77011112233")
        call = CallRecord.objects.get(pk=response.data["call_id"])
        self.assertEqual(call.direction, CallRecord.Direction.OUTBOUND)
        self.assertEqual(call.status, CallRecord.Status.EXTERNAL)
        self.assertEqual(call.employee, self.owner)
        self.assertEqual(call.child, self.child)
        self.assertTrue(call.communication_log_id)

    @patch("domains.platform.notifications.messaging.telephony._zadarma_request")
    def test_zadarma_outgoing_uses_callback_api(self, request_callback):
        TelephonyConnection.objects.create(
            organization=self.org,
            provider=TelephonyConnection.Provider.ZADARMA,
            api_key="key",
            api_secret="secret",
            virtual_number="101",
        )
        request_callback.return_value = {"status": "success"}
        response = self.api.post(
            "/api/v1/messaging/telephony/outgoing/",
            {"phone": "+77011112233"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["started"])
        request_callback.assert_called_once()
        self.assertEqual(
            CallRecord.objects.get(pk=response.data["call_id"]).status,
            CallRecord.Status.RINGING,
        )

    def test_me_can_call_only_with_configured_pbx(self):
        """Кнопки «Позвонить» в CRM — только когда звонок пойдёт через АТС."""
        self.assertFalse(self.api.get("/api/v1/users/auth/me/").data["can_call"])
        connection = TelephonyConnection.objects.create(
            organization=self.org,
            provider=TelephonyConnection.Provider.ZADARMA,
            api_key="key",
            api_secret="secret",
        )
        self.assertFalse(self.api.get("/api/v1/users/auth/me/").data["can_call"])
        connection.virtual_number = "101"
        connection.save()
        self.assertTrue(self.api.get("/api/v1/users/auth/me/").data["can_call"])
        teacher = User.objects.create_user(
            phone="77010000009",
            password="p",
            full_name="Педагог",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        self.api.force_authenticate(teacher)
        self.assertFalse(self.api.get("/api/v1/users/auth/me/").data["can_call"])

    def test_zadarma_webhook_echo_and_signature(self):
        connection = TelephonyConnection.objects.create(
            organization=self.org,
            provider=TelephonyConnection.Provider.ZADARMA,
            api_key="key",
            api_secret="secret",
            webhook_secret="webhook-secret",
        )
        echo = self.api.get(
            f"/api/v1/messaging/telephony/webhook/{connection.webhook_secret}/",
            {"zd_echo": "verified"},
        )
        self.assertEqual(echo.status_code, 200)
        self.assertEqual(echo.content, b"verified")
        payload = {
            "event": "NOTIFY_START",
            "pbx_call_id": "pbx-1",
            "caller_id": "77011112233",
            "called_did": "77270000000",
            "call_start": "2026-10-14 10:00:00",
        }
        signature = base64.b64encode(
            hmac.new(
                b"secret",
                b"77011112233772700000002026-10-14 10:00:00",
                hashlib.sha1,
            ).digest()
        ).decode()
        self.assertTrue(valid_zadarma_webhook_signature(payload, signature, "secret"))
        response = self.api.post(
            f"/api/v1/messaging/telephony/webhook/{connection.webhook_secret}/",
            payload,
            format="json",
            HTTP_SIGNATURE=signature,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(CallRecord.objects.get(provider_call_id="pbx-1").status, "ringing")
