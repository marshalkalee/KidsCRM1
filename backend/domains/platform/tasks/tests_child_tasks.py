import datetime
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from domains.people.clients.models import Child
from domains.platform.leads.models import Lead
from domains.platform.tenants.models import Branch, Organization
from domains.platform.users.models import User

from .models import Task
from .services import cancel_task, complete_task, create_task

URL = "/api/v1/tasks/for-child/"


def make_child(organization, name):
    return Child.objects.create(
        organization=organization,
        full_name=name,
        birth_date=datetime.date(2018, 1, 1),
        gender=Child.Gender.MALE,
    )


def make_user(organization, phone, role, branches=()):
    user = User.objects.create_user(
        phone=phone,
        password="pass",
        full_name=f"Сотрудник {phone[-2:]}",
        organization=organization,
        role=role,
    )
    user.branches.set(branches)
    return user


class ChildTasksTabApiTests(TestCase):
    """TRU-112: вкладка «Задачи» карточки ребёнка."""

    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.branch = Branch.objects.create(organization=self.org, name="Филиал А")
        self.other_branch = Branch.objects.create(organization=self.org, name="Филиал Б")
        self.admin = make_user(self.org, "77001110001", User.Role.ADMIN, [self.branch])
        self.other_admin = make_user(self.org, "77001110002", User.Role.ADMIN, [self.other_branch])
        self.owner = make_user(self.org, "77001110003", User.Role.OWNER)
        self.teacher = make_user(self.org, "77001110004", User.Role.TEACHER)
        self.child = make_child(self.org, "Алихан")
        self.other_child = make_child(self.org, "Другой ребёнок")
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def task(self, **kwargs):
        params = {
            "type": Task.Type.CALL_BACK,
            "assignee": self.admin,
            "due_date": None,
            "subject": "Задача",
            "branch": self.branch,
        }
        params.update(kwargs)
        return create_task(**params)

    def get(self, child=None, user=None):
        api = APIClient()
        api.force_authenticate(user or self.admin)
        response = api.get(URL, {"child": str((child or self.child).id)})
        self.assertEqual(response.status_code, 200, response.content)
        return response.data

    def test_includes_tasks_by_child_and_by_source_and_renewal_leads(self):
        source_lead = Lead.objects.create(
            organization=self.org,
            parent_name="Родитель",
            phone="77011110001",
            branch=self.branch,
            converted_child=self.child,
        )
        renewal_lead = Lead.objects.create(
            organization=self.org,
            parent_name="Родитель",
            phone="77011110002",
            branch=self.branch,
            kind=Lead.Kind.RENEWAL,
            child=self.child,
        )
        self.task(subject="по ребёнку", child=self.child)
        self.task(subject="по исходной заявке", lead=source_lead)
        self.task(subject="по продлению", lead=renewal_lead)
        self.task(subject="другой ребёнок", child=self.other_child)

        titles = {row["title"] for row in self.get()["open"]}

        self.assertEqual(titles, {"по ребёнку", "по исходной заявке", "по продлению"})

    def test_splits_open_and_closed_and_keeps_closing_comment(self):
        self.task(subject="открытая", child=self.child)
        done = self.task(subject="выполнена", child=self.child)
        complete_task(done, actor=self.admin, comment="Дозвонился, придут в субботу")
        cancelled = self.task(subject="отменена", child=self.child)
        cancel_task(cancelled, actor=self.admin, comment="Дубль")

        data = self.get()

        self.assertEqual([row["title"] for row in data["open"]], ["открытая"])
        closed = {row["title"]: row for row in data["closed"]}
        self.assertEqual(set(closed), {"выполнена", "отменена"})
        self.assertEqual(closed["выполнена"]["status"], "done")
        self.assertEqual(closed["выполнена"]["closing_comment"], "Дозвонился, придут в субботу")
        self.assertEqual(closed["отменена"]["status"], "cancelled")
        self.assertEqual(data["closed_total"], 2)

    def test_open_tasks_are_sorted_by_deadline_without_deadline_last(self):
        now = timezone.now()
        self.task(subject="без срока", child=self.child)
        self.task(subject="через два дня", child=self.child, due_date=now + timedelta(days=2))
        self.task(subject="завтра", child=self.child, due_date=now + timedelta(days=1))

        titles = [row["title"] for row in self.get()["open"]]

        self.assertEqual(titles, ["завтра", "через два дня", "без срока"])

    def test_closed_history_is_newest_first_and_limited(self):
        for title in ("закрыта первой", "закрыта второй", "закрыта третьей"):
            complete_task(self.task(subject=title, child=self.child), actor=self.admin)

        with patch("domains.platform.tasks.views.CLOSED_HISTORY_LIMIT", 2):
            data = self.get()

        self.assertEqual(
            [row["title"] for row in data["closed"]], ["закрыта третьей", "закрыта второй"]
        )
        self.assertEqual(data["closed_total"], 3)

    def test_task_in_another_branch_is_hidden_from_branch_admin_but_visible_to_owner(self):
        self.task(
            subject="чужой филиал",
            child=self.child,
            assignee=self.other_admin,
            branch=self.other_branch,
        )

        self.assertEqual(self.get()["open"], [])
        self.assertEqual(
            [row["title"] for row in self.get(user=self.owner)["open"]], ["чужой филиал"]
        )

    def test_other_organization_is_isolated(self):
        other_org = Organization.objects.create(name="Другой центр", slug="other")
        other_admin = make_user(other_org, "77009990000", User.Role.ADMIN)
        foreign_child = make_child(other_org, "Чужой ребёнок")
        create_task(
            type=Task.Type.OTHER,
            assignee=other_admin,
            due_date=None,
            subject="чужая",
            organization=other_org,
            child=foreign_child,
        )

        data = self.get(child=foreign_child)

        self.assertEqual((data["open"], data["closed"], data["closed_total"]), ([], [], 0))

    def test_teacher_has_no_access(self):
        api = APIClient()
        api.force_authenticate(self.teacher)

        response = api.get(URL, {"child": str(self.child.id)})

        self.assertEqual(response.status_code, 403)

    def test_child_param_is_required_and_must_be_uuid(self):
        self.assertEqual(self.api.get(URL).status_code, 400)
        self.assertEqual(self.api.get(URL, {"child": "not-a-uuid"}).status_code, 400)

    def test_task_created_from_card_shows_up_in_tab_and_my_tasks(self):
        due_at = (timezone.now() + timedelta(hours=1)).isoformat()

        response = self.api.post(
            "/api/v1/tasks/",
            {
                "type": "call_back",
                "title": "Перезвонить: Алихан",
                "description": "Спросить про пробное",
                "child": str(self.child.id),
                "branch": str(self.branch.id),
                "assigned_to": str(self.admin.id),
                "due_at": due_at,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual([row["title"] for row in self.get()["open"]], ["Перезвонить: Алихан"])
        mine = self.api.get("/api/v1/tasks/", {"assigned_to": str(self.admin.id), "status": "open"})
        rows = mine.data["results"] if "results" in mine.data else mine.data
        self.assertIn("Перезвонить: Алихан", [row["title"] for row in rows])

    def test_cannot_attach_task_to_foreign_child_or_assignee(self):
        other_org = Organization.objects.create(name="Другой центр", slug="other")
        foreign_child = make_child(other_org, "Чужой ребёнок")
        foreign_user = make_user(other_org, "77009990001", User.Role.ADMIN)

        for field, value in (("child", foreign_child.id), ("assigned_to", foreign_user.id)):
            payload = {"type": "other", "title": "Подмена", "assigned_to": str(self.admin.id)}
            payload[field] = str(value)

            response = self.api.post("/api/v1/tasks/", payload, format="json")

            self.assertEqual(response.status_code, 400, field)
            self.assertIn(field, response.data)
        self.assertEqual(Task.objects.count(), 0)
