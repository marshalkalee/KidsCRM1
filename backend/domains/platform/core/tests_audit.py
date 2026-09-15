from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from domains.platform.core.audit import AuditLog
from domains.platform.tenants.models import Branch, Organization
from domains.platform.users.models import User


def make_client(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    refresh["organization_id"] = str(user.organization_id)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")
    return client


class AuditLogTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Балет Астана", slug="ballet-astana")
        self.user = User.objects.create_user(
            phone="77001234567",
            password="pass",
            full_name="Владелец",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.branch = Branch.objects.create(name="Центральный", organization=self.org)
        self.client = make_client(self.user)

    def test_record_creates_audit_entry(self):
        AuditLog.record(
            actor=self.user,
            action=AuditLog.Action.UPDATE,
            entity=self.branch,
            before={"name": "Старое название"},
            after={"name": "Новое название"},
        )
        self.assertEqual(AuditLog.objects.count(), 1)
        log = AuditLog.objects.first()
        self.assertEqual(log.action, AuditLog.Action.UPDATE)
        self.assertEqual(log.before["name"], "Старое название")
        self.assertEqual(log.after["name"], "Новое название")

    def test_audit_log_cannot_be_deleted(self):
        AuditLog.record(
            actor=self.user,
            action=AuditLog.Action.CREATE,
            entity=self.branch,
        )
        log = AuditLog.objects.first()
        with self.assertRaises(PermissionError):
            log.delete()

    def test_audit_log_cannot_be_edited(self):
        AuditLog.record(
            actor=self.user,
            action=AuditLog.Action.CREATE,
            entity=self.branch,
        )
        log = AuditLog.objects.first()
        log.action = AuditLog.Action.DELETE
        with self.assertRaises(PermissionError):
            log.save()

    def test_audit_api_returns_org_logs(self):
        AuditLog.record(
            actor=self.user,
            action=AuditLog.Action.UPDATE,
            entity=self.branch,
            before={"name": "Старое"},
            after={"name": "Новое"},
        )
        response = self.client.get("/api/v1/audit/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_audit_api_filters_by_entity(self):
        AuditLog.record(
            actor=self.user,
            action=AuditLog.Action.UPDATE,
            entity=self.branch,
        )
        response = self.client.get("/api/v1/audit/?entity_type=branch")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_audit_api_is_readonly(self):
        response = self.client.post("/api/v1/audit/", {"action": "delete"})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
