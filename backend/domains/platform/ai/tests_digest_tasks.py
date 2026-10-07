import datetime
from unittest import mock

from django.test import override_settings
from django.utils import timezone

from domains.people.clients.models import Child
from domains.platform.tasks.models import Task
from domains.platform.tenants.models import Branch
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group, GroupMembership

from . import digest_tasks
from .models import AIDigest
from .tests import AIFixtures
from .tests_usage import OPENAI


@override_settings(**OPENAI)
class DigestTaskTests(AIFixtures):
    def setUp(self):
        super().setUp()
        self.item = {
            "id": "occupancy.группы[0].процент",
            "title": "Дозаполнить группу",
            "action": "Связаться с семьями",
            "rationale": "В группе есть свободные места",
            "priority": "high",
            "evidence": [],
        }
        self.digest = AIDigest.objects.create(
            organization=self.org,
            week_start=datetime.date(2026, 10, 5),
            trigger=AIDigest.Trigger.SCHEDULE,
            status=AIDigest.Status.READY,
            ready_at=timezone.now(),
            content={"items": [self.item], "highlights": [self.item], "blocks": []},
        )
        self.url = f"/api/v1/ai/digests/{self.digest.id}"

    def test_general_task_is_created_only_after_click_and_is_idempotent(self):
        self.assertFalse(Task.objects.exists())
        preview = self.client_api.post(
            f"{self.url}/task-preview/",
            {"item_id": self.item["id"], "task_type": Task.Type.OTHER},
            format="json",
        )
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertEqual(preview.data["new_count"], 1)
        self.assertFalse(Task.objects.exists())

        payload = {
            "item_id": self.item["id"],
            "task_type": Task.Type.OTHER,
            "due_at": (timezone.now() + datetime.timedelta(hours=2)).isoformat(),
        }
        first = self.client_api.post(f"{self.url}/tasks/", payload, format="json")
        second = self.client_api.post(f"{self.url}/tasks/", payload, format="json")
        self.assertEqual(first.data, {"created": 1, "skipped": 0})
        self.assertEqual(second.data, {"created": 0, "skipped": 1})
        task = Task.objects.get()
        self.assertEqual(task.assigned_to, self.owner)
        self.assertIn("Из дайджеста", task.description)
        self.assertIn(f"/digest?id={self.digest.id}", task.description)

    def test_equal_reason_and_recommendation_are_not_duplicated(self):
        self.item["rationale"] = self.item["action"]
        self.digest.content = {"items": [self.item], "highlights": [self.item], "blocks": []}
        self.digest.save(update_fields=["content"])

        response = self.client_api.post(
            f"{self.url}/tasks/",
            {
                "item_id": self.item["id"],
                "task_type": Task.Type.OTHER,
                "due_at": (timezone.now() + datetime.timedelta(hours=2)).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        description = Task.objects.get().description
        self.assertNotIn("Основание:", description)
        self.assertEqual(description.count("Связаться с семьями"), 1)

    @mock.patch("domains.platform.ai.digest_tasks.risk_list")
    def test_child_names_come_from_crm_and_branch_admin_is_default(self, risk):
        branch = Branch.objects.create(organization=self.org, name="Алмалы")
        admin = User.objects.create_user(
            organization=self.org,
            phone="+77010000991",
            password="x",
            full_name="Администратор Алмалы",
            role=User.Role.ADMIN,
        )
        admin.branches.add(branch)
        group = Group.objects.create(
            organization=self.org,
            branch=branch,
            direction=self.ballet,
            name="Балет 7–9",
            capacity=12,
        )
        child = Child.objects.create(
            organization=self.org,
            full_name="Милана Исаева",
            birth_date=datetime.date(2018, 1, 1),
        )
        GroupMembership.objects.create(
            organization=self.org,
            group=group,
            child=child,
            joined_at=datetime.date(2026, 1, 1),
        )
        other_branch = Branch.objects.create(organization=self.org, name="Орбита")
        other_group = Group.objects.create(
            organization=self.org,
            branch=other_branch,
            direction=self.ballet,
            name="Балет 10–14",
            capacity=12,
        )
        other_child = Child.objects.create(
            organization=self.org,
            full_name="Ребёнок другой группы",
            birth_date=datetime.date(2015, 1, 1),
        )
        GroupMembership.objects.create(
            organization=self.org,
            group=other_group,
            child=other_child,
            joined_at=datetime.date(2026, 1, 1),
        )
        self.item["evidence"] = [
            {
                "key": self.item["id"],
                "label": "Заполняемость · Балет 7–9, Алмалы: заполняемость, %",
                "value": 40,
            }
        ]
        self.digest.content = {
            "items": [self.item],
            "highlights": [self.item],
            "blocks": [],
        }
        self.digest.save(update_fields=["content"])
        risk.return_value = {
            "items": [
                {
                    "id": str(child.id),
                    "name": child.full_name,
                    "signals": ["attendance"],
                },
                {
                    "id": str(other_child.id),
                    "name": other_child.full_name,
                    "signals": ["attendance"],
                },
            ]
        }

        response = self.client_api.post(
            f"{self.url}/task-preview/",
            {"item_id": self.item["id"], "task_type": Task.Type.RETENTION},
            format="json",
        )
        row = response.data["items"][0]
        self.assertEqual(len(response.data["items"]), 1)
        self.assertEqual(row["child_name"], child.full_name)
        self.assertEqual(row["assignee_id"], str(admin.id))
        self.assertNotIn(child.full_name, str(self.digest.content))

    @mock.patch("domains.platform.ai.digest_tasks.risk_list", return_value={"items": []})
    def test_human_leave_reason_is_excluded_from_return_list(self, _risk):
        Child.objects.create(
            organization=self.org,
            full_name="Переехавший ребёнок",
            birth_date=datetime.date(2018, 1, 1),
            status=Child.Status.LEFT,
            leave_reason="Переезд в другой город",
        )
        callable_child = Child.objects.create(
            organization=self.org,
            full_name="Можно вернуть",
            birth_date=datetime.date(2018, 1, 1),
            status=Child.Status.LEFT,
            leave_reason="Стало дорого",
        )
        rows = digest_tasks._candidate_children(self.org, Task.Type.RETENTION)
        self.assertEqual([row["id"] for row in rows], [str(callable_child.id)])

    def test_dismissed_recommendation_is_hidden_and_cannot_create_task(self):
        response = self.client_api.post(
            f"{self.url}/dismiss/", {"item_id": self.item["id"]}, format="json"
        )
        self.assertEqual(response.status_code, 204)
        detail = self.client_api.get(f"{self.url}/")
        self.assertEqual(detail.data["content"]["items"], [])
        preview = self.client_api.post(
            f"{self.url}/task-preview/",
            {"item_id": self.item["id"], "task_type": Task.Type.OTHER},
            format="json",
        )
        self.assertEqual(preview.status_code, 400)
