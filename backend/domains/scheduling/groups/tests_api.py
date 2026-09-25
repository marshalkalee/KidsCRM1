"""
API групп для frontend2 (TRU-87): изоляция организаций в выборе филиала/
направления/преподавателей/ребёнка, архивное направление у существующей
группы (TRU-77), недозаполненность по порогу организации, состав.
"""

import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase, tag
from django.urls import reverse
from rest_framework.test import APIClient

from domains.people.clients.models import Child
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.tenants.org_settings import GROUP_UNDERFILLED_PERCENT_THRESHOLD

from .models import Group, GroupMembership

User = get_user_model()
LIST = reverse("group-list")


def detail(group, suffix=""):
    return reverse(f"group-{suffix or 'detail'}", args=[group.pk])


class GroupApiTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(
            name="True Ballet",
            slug="true-ballet",
            settings={GROUP_UNDERFILLED_PERCENT_THRESHOLD: 50},
        )
        self.owner = self.user("+77010000001", User.Role.OWNER)
        self.teacher = self.user("+77010000002", User.Role.TEACHER, "Динара")
        self.teacher2 = self.user("+77010000003", User.Role.TEACHER, "Алия")
        self.branch = Branch.objects.create(organization=self.org, name="Центр")
        self.direction = Direction.objects.create(organization=self.org, name="Балет")
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def user(self, phone, role, name="User", org=None):
        return User.objects.create_user(
            phone=phone,
            full_name=name,
            password="pass12345",
            organization=org or self.org,
            role=role,
        )

    def group(self, **extra):
        return Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name=extra.pop("name", "Младшая"),
            capacity=extra.pop("capacity", 10),
            **extra,
        )

    def child(self, name="Аружан", org=None):
        return Child.objects.create(
            organization=org or self.org,
            full_name=name,
            birth_date=datetime.date(2018, 1, 1),
            gender=Child.Gender.FEMALE,
        )

    def test_create_with_two_teachers(self):
        response = self.api.post(
            LIST,
            {
                "name": "Балет 4–6",
                "branch": str(self.branch.id),
                "direction": str(self.direction.id),
                "teachers": [str(self.teacher.id), str(self.teacher2.id)],
                "capacity": 12,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual(
            sorted(t["full_name"] for t in data["teachers_detail"]), ["Алия", "Динара"]
        )
        self.assertEqual(data["branch_name"], "Центр")

    @tag("tenant_isolation")
    def test_cannot_use_other_organizations_branch_teacher_or_child(self):
        other = Organization.objects.create(name="Other", slug="other")
        foreign_branch = Branch.objects.create(organization=other, name="Чужой")
        foreign_teacher = self.user("+77010000099", User.Role.TEACHER, org=other)
        foreign_child = self.child("Чужой", org=other)

        created = self.api.post(
            LIST,
            {
                "name": "X",
                "branch": str(foreign_branch.id),
                "direction": str(self.direction.id),
                "teachers": [str(foreign_teacher.id)],
                "capacity": 5,
            },
            format="json",
        )
        added = self.api.post(
            detail(self.group(), "add-member"), {"child": str(foreign_child.id)}, format="json"
        )

        self.assertEqual(created.status_code, 400)
        self.assertIn("branch", created.json())
        self.assertIn("teachers", created.json())
        self.assertEqual(added.status_code, 400)

    def test_group_with_archived_direction_is_editable(self):
        group = self.group()
        self.direction.is_active = False
        self.direction.save()

        response = self.api.patch(detail(group), {"capacity": 15}, format="json")
        new_group = self.api.post(
            LIST,
            {
                "name": "Новая",
                "branch": str(self.branch.id),
                "direction": str(self.direction.id),
                "capacity": 5,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(new_group.status_code, 400)

    def test_underfilled_uses_org_threshold(self):
        group = self.group(capacity=10)
        for i in range(4):
            GroupMembership.objects.create(
                organization=self.org,
                group=group,
                child=self.child(f"Ребёнок {i}"),
                joined_at=datetime.date.today(),
            )

        data = self.api.get(detail(group)).json()

        self.assertEqual((data["members_count"], data["fill_percent"]), (4, 40))
        self.assertTrue(data["is_underfilled"])

    def test_teacher_sees_only_own_groups(self):
        mine = self.group(name="Моя")
        mine.teachers.add(self.teacher)
        self.group(name="Чужая")
        self.api.force_authenticate(self.teacher)

        rows = self.api.get(LIST).json()["results"]

        self.assertEqual([g["name"] for g in rows], ["Моя"])

    def test_add_member_twice_and_over_capacity_are_clean_errors(self):
        group = self.group(capacity=1)
        kid = self.child()

        first = self.api.post(detail(group, "add-member"), {"child": str(kid.id)}, format="json")
        again = self.api.post(detail(group, "add-member"), {"child": str(kid.id)}, format="json")
        full = self.api.post(
            detail(group, "add-member"), {"child": str(self.child("Вторая").id)}, format="json"
        )

        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(first.json()["joined_at"], str(datetime.date.today()))
        self.assertEqual(again.status_code, 400)
        self.assertEqual(full.status_code, 400)
        self.assertIn("мест", str(full.json()))

    def test_remove_member_defaults_to_today_and_keeps_history(self):
        group = self.group()
        kid = self.child()
        GroupMembership.objects.create(
            organization=self.org, group=group, child=kid, joined_at=datetime.date(2026, 1, 1)
        )

        self.api.post(detail(group, "remove-member"), {"child_id": str(kid.id)}, format="json")

        members = self.api.get(detail(group, "members")).json()
        history = self.api.get(detail(group, "history")).json()
        self.assertEqual(members, [])
        self.assertEqual(history[0]["left_at"], str(datetime.date.today()))

    def test_close_keeps_group(self):
        group = self.group()

        self.api.delete(detail(group))

        group.refresh_from_db()
        self.assertEqual(group.status, Group.Status.CLOSED)
