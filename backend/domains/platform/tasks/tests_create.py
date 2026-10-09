"""Новая задача со страницы «Задачи» (TRU-181)."""

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from domains.platform.core.audit import AuditLog
from domains.platform.tenants.models import Branch, Organization
from domains.platform.users.models import User

from .models import Task

URL = "/api/v1/tasks/"


class CreateTaskTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Центр", slug="new-task")
        self.a = Branch.objects.create(organization=self.org, name="Алмалы")
        self.b = Branch.objects.create(organization=self.org, name="Орбита")
        self.owner = self.user("77040000001", User.Role.OWNER)
        self.admin_a = self.user("77040000002", User.Role.ADMIN, [self.a])
        self.admin_b = self.user("77040000003", User.Role.ADMIN, [self.b])
        self.manager_all = self.user("77040000004", User.Role.MANAGER)

    def user(self, phone, role, branches=()):
        user = User.objects.create_user(
            phone=phone, password="p", full_name=phone, organization=self.org, role=role
        )
        user.branches.set(branches)
        return user

    def post(self, user, **data):
        client = APIClient()
        client.force_authenticate(user)
        payload = {"type": "other", "title": "Подготовить костюмы", **data}
        return client.post(URL, payload, format="json")

    def test_task_without_child_or_lead_is_visible_to_assignee(self):
        response = self.post(
            self.owner, assigned_to=str(self.admin_a.id), due_at=timezone.now().isoformat()
        )
        self.assertEqual(response.status_code, 201, response.data)
        client = APIClient()
        client.force_authenticate(self.admin_a)
        data = client.get(URL, {"assigned_to": self.admin_a.id}).data
        rows = data["results"] if isinstance(data, dict) else data
        ids = {row["id"] for row in rows}
        self.assertIn(response.data["id"], ids)
        task = Task.objects.get(pk=response.data["id"])
        self.assertEqual(task.source, Task.Source.MANUAL)
        self.assertTrue(
            AuditLog.objects.filter(object_id=task.pk, action=AuditLog.Action.CREATE).exists()
        )

    def test_admin_cannot_assign_to_staff_of_another_branch(self):
        response = self.post(self.admin_a, assigned_to=str(self.admin_b.id))
        self.assertEqual(response.status_code, 400)
        self.assertIn("assigned_to", response.data)
        # Тому, кто работает во всех филиалах, — можно.
        ok = self.post(self.admin_a, assigned_to=str(self.manager_all.id))
        self.assertEqual(ok.status_code, 201, ok.data)

    def test_admin_cannot_put_task_into_foreign_branch(self):
        response = self.post(self.admin_a, branch=str(self.b.id))
        self.assertEqual(response.status_code, 400)
        self.assertIn("branch", response.data)
