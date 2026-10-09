from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from domains.people.clients.models import Child
from domains.platform.leads.models import Lead
from domains.platform.tenants.models import Branch, Organization
from domains.platform.users.models import User

from .models import Task
from .services import complete_task, create_task, visible_tasks


class TaskServiceTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.other_org = Organization.objects.create(name="Другой центр", slug="other")
        self.branch_a = Branch.objects.create(organization=self.org, name="Филиал А")
        self.branch_b = Branch.objects.create(organization=self.org, name="Филиал Б")

        self.owner = User.objects.create_user(
            phone="77001110001",
            password="pass",
            full_name="Владелец",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.manager = User.objects.create_user(
            phone="77001110002",
            password="pass",
            full_name="Управляющий",
            organization=self.org,
            role=User.Role.MANAGER,
        )
        self.manager.branches.set([self.branch_a])
        self.admin_a = User.objects.create_user(
            phone="77001110003",
            password="pass",
            full_name="Админ А",
            organization=self.org,
            role=User.Role.ADMIN,
        )
        self.admin_a.branches.set([self.branch_a])
        self.admin_b = User.objects.create_user(
            phone="77001110004",
            password="pass",
            full_name="Админ Б",
            organization=self.org,
            role=User.Role.ADMIN,
        )
        self.admin_b.branches.set([self.branch_b])
        self.teacher = User.objects.create_user(
            phone="77001110005",
            password="pass",
            full_name="Препод",
            organization=self.org,
            role=User.Role.TEACHER,
        )

    def test_create_task_via_service(self):
        task = create_task(
            type=Task.Type.PAYMENT_REMINDER,
            assignee=self.admin_a,
            due_date=timezone.now() + timedelta(days=1),
            subject="Напомнить про оплату",
            branch=self.branch_a,
        )
        self.assertEqual(task.status, Task.Status.OPEN)
        self.assertEqual(task.source, Task.Source.MANUAL)

    def test_tenant_isolation(self):
        other_admin = User.objects.create_user(
            phone="77009990000",
            password="pass",
            full_name="Чужой админ",
            organization=self.other_org,
            role=User.Role.ADMIN,
        )
        create_task(
            type=Task.Type.OTHER,
            assignee=other_admin,
            due_date=None,
            subject="Чужая задача",
            organization=self.other_org,
        )
        create_task(
            type=Task.Type.OTHER,
            assignee=self.admin_a,
            due_date=None,
            subject="Своя задача",
            branch=self.branch_a,
        )
        self.assertEqual(visible_tasks(self.admin_a).count(), 1)

    def test_owner_sees_all_branches(self):
        create_task(
            type=Task.Type.OTHER,
            assignee=self.admin_a,
            due_date=None,
            subject="А",
            branch=self.branch_a,
        )
        create_task(
            type=Task.Type.OTHER,
            assignee=self.admin_b,
            due_date=None,
            subject="Б",
            branch=self.branch_b,
        )
        self.assertEqual(visible_tasks(self.owner).count(), 2)

    def test_admin_sees_own_branch_and_own_assigned(self):
        create_task(
            type=Task.Type.OTHER,
            assignee=self.admin_a,
            due_date=None,
            subject="Моя, мой филиал",
            branch=self.branch_a,
        )
        create_task(
            type=Task.Type.OTHER,
            assignee=self.admin_b,
            due_date=None,
            subject="Чужая, чужой филиал",
            branch=self.branch_b,
        )
        create_task(
            type=Task.Type.OTHER,
            assignee=self.admin_b,
            due_date=None,
            subject="Назначена на меня, но филиал Б",
            branch=self.branch_b,
        )
        Task.objects.filter(title="Назначена на меня, но филиал Б").update(assigned_to=self.admin_a)

        visible_titles = set(visible_tasks(self.admin_a).values_list("title", flat=True))
        self.assertIn("Моя, мой филиал", visible_titles)
        self.assertNotIn("Чужая, чужой филиал", visible_titles)
        self.assertIn("Назначена на меня, но филиал Б", visible_titles)

    def test_lead_and_child_linkage_both_directions(self):
        child = Child.objects.create(
            organization=self.org,
            full_name="Тест Тестов",
            birth_date="2018-01-01",
            gender=Child.Gender.MALE,
        )
        lead = Lead.objects.create(
            organization=self.org, parent_name="Родитель", phone="77011112222"
        )
        task = create_task(
            type=Task.Type.CALL_BACK,
            assignee=self.admin_a,
            due_date=None,
            subject="Т",
            lead=lead,
            child=child,
            branch=self.branch_a,
        )
        self.assertIn(task, lead.tasks.all())
        self.assertIn(task, child.tasks.all())

    def test_complete_and_cancel_set_status_and_comment(self):
        task = create_task(type=Task.Type.OTHER, assignee=self.admin_a, due_date=None, subject="Т")
        complete_task(task, actor=self.admin_a, comment="Дозвонился")
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.DONE)
        self.assertEqual(task.closing_comment, "Дозвонился")

    def test_teacher_sees_only_own_tasks(self):
        """Преподаватель получает поручения (TRU-181), но чужих задач не видит
        и задачи по карточке ребёнка ему недоступны."""
        client = APIClient()
        client.force_authenticate(self.teacher)
        response = client.get("/api/v1/tasks/")
        self.assertEqual(response.status_code, 200)
        rows = response.data["results"] if isinstance(response.data, dict) else response.data
        self.assertTrue(all(row["assigned_to"] == self.teacher.id for row in rows))
        self.assertEqual(client.get("/api/v1/tasks/for-child/").status_code, 403)

    def test_admin_can_create_task_via_api(self):
        client = APIClient()
        client.force_authenticate(self.admin_a)
        response = client.post(
            "/api/v1/tasks/",
            {
                "type": "call_back",
                "title": "Перезвонить",
                "assigned_to": self.admin_a.id,
                "branch": self.branch_a.id,
            },
        )
        self.assertEqual(response.status_code, 201, response.content)


class ManualAutoDuplicatePreventionTests(TestCase):
    """TRU-111: ручное создание задачи через API-паттерн кнопки (сначала
    GET-проверка на уже открытую, потом POST) не плодит дубль поверх уже
    существующей автозадачи на ту же заявку."""

    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.branch = Branch.objects.create(organization=self.org, name="Филиал на Абая")
        self.admin = User.objects.create_user(
            phone="77001112233",
            password="pass",
            full_name="Админ",
            organization=self.org,
            role=User.Role.ADMIN,
        )
        self.admin.branches.set([self.branch])
        self.lead = Lead.objects.create(
            organization=self.org,
            parent_name="Родитель",
            phone="77011112222",
            branch=self.branch,
            assigned_to=self.admin,
        )

    def test_manual_create_skips_when_auto_task_already_open(self):
        from domains.platform.leads.rules import create_tasks_for_stale_leads
        from domains.platform.tenants.org_settings import RULE_LEAD_STALE_ENABLED

        self.org.settings = {**self.org.settings, RULE_LEAD_STALE_ENABLED: True}
        self.org.save(update_fields=["settings"])
        Lead.objects.filter(pk=self.lead.pk).update(
            status_changed_at=timezone.now() - timedelta(days=10)
        )
        create_tasks_for_stale_leads()
        self.assertEqual(Task.objects.filter(lead=self.lead).count(), 1)

        client = APIClient()
        client.force_authenticate(self.admin)
        existing = client.get(
            "/api/v1/tasks/", {"lead": str(self.lead.id), "type": "call_back", "status": "open"}
        )
        found = existing.data["results"] if "results" in existing.data else existing.data
        self.assertEqual(len(found), 1)
        # Кнопка на этом шаге НЕ отправляет POST — ровно это и тестируем:
        # что проверка нашла существующую задачу, значит дубль не создаётся.
        self.assertEqual(Task.objects.filter(lead=self.lead).count(), 1)

    def test_manual_create_proceeds_when_nothing_open(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        existing = client.get(
            "/api/v1/tasks/", {"lead": str(self.lead.id), "type": "call_back", "status": "open"}
        )
        found = existing.data["results"] if "results" in existing.data else existing.data
        self.assertEqual(len(found), 0)

        response = client.post(
            "/api/v1/tasks/",
            {
                "type": "call_back",
                "title": "Перезвонить: Родитель",
                "lead": str(self.lead.id),
                "branch": str(self.branch.id),
                "assigned_to": str(self.admin.id),
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Task.objects.filter(lead=self.lead).count(), 1)
