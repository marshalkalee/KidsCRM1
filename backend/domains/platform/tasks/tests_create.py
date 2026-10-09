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


class OwnTasksTests(CreateTaskTests):
    """Бухгалтер и преподаватель получают задачи и работают со своими."""

    def setUp(self):
        super().setUp()
        self.teacher = self.user("77040000005", User.Role.TEACHER)
        self.accountant = self.user("77040000006", User.Role.ACCOUNTANT)

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def rows(self, user):
        data = self.client_for(user).get(URL).data
        return data["results"] if isinstance(data, dict) else data

    def test_teacher_sees_and_closes_only_own_tasks(self):
        own = self.post(self.owner, assigned_to=str(self.teacher.id)).data["id"]
        other = self.post(self.owner, assigned_to=str(self.admin_a.id)).data["id"]
        self.assertEqual({row["id"] for row in self.rows(self.teacher)}, {own})
        client = self.client_for(self.teacher)
        tomorrow = (timezone.now() + timezone.timedelta(days=1)).isoformat()
        self.assertEqual(
            client.patch(f"{URL}{own}/", {"due_at": tomorrow}, format="json").status_code, 200
        )
        self.assertEqual(client.post(f"{URL}{own}/complete/").status_code, 200)
        self.assertEqual(client.post(f"{URL}{other}/complete/").status_code, 404)

    def test_accountant_completes_own_task_but_cannot_reassign(self):
        own = self.post(self.owner, assigned_to=str(self.accountant.id)).data["id"]
        client = self.client_for(self.accountant)
        reassign = client.patch(f"{URL}{own}/", {"assigned_to": str(self.owner.id)}, format="json")
        self.assertEqual(reassign.status_code, 403)
        self.assertEqual(client.post(f"{URL}{own}/complete/").status_code, 200)

    def test_teacher_cannot_create_tasks(self):
        self.assertEqual(self.post(self.teacher).status_code, 403)
