"""Сотрудник с выбранными филиалами работает только в них."""

import datetime

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from domains.people.clients.models import Child
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group, GroupMembership

TODAY = timezone.localdate()


class BranchScopeTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Центр", slug="scope")
        self.a = Branch.objects.create(organization=self.org, name="Алмалы")
        self.b = Branch.objects.create(organization=self.org, name="Орбита")
        self.owner = self.user("77030000001", User.Role.OWNER)
        self.admin_a = self.user("77030000002", User.Role.ADMIN, [self.a])
        self.teacher_b = self.user("77030000003", User.Role.TEACHER, [self.b])
        self.admin_all = self.user("77030000004", User.Role.ADMIN)
        direction = Direction.objects.create(organization=self.org, name="Балет")
        self.group_a = self.group("Балет А", self.a, direction)
        self.group_b = self.group("Балет Б", self.b, direction)
        self.child("Аня", self.group_a)
        self.child("Белла", self.group_b)

    def user(self, phone, role, branches=()):
        user = User.objects.create_user(
            phone=phone, password="p", full_name=phone, organization=self.org, role=role
        )
        user.branches.set(branches)
        return user

    def group(self, name, branch, direction):
        return Group.objects.create(
            organization=self.org, branch=branch, direction=direction, name=name, capacity=10
        )

    def child(self, name, group):
        child = Child.objects.create(
            organization=self.org, full_name=name, birth_date=datetime.date(2018, 1, 1)
        )
        GroupMembership.objects.create(
            organization=self.org, group=group, child=child, joined_at=TODAY
        )

    def get(self, user, url, **headers):
        client = APIClient()
        client.force_authenticate(user)
        response = client.get(url, **headers)
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data
        return data["results"] if isinstance(data, dict) and "results" in data else data

    def names(self, rows, key="name"):
        return {row[key] for row in rows}

    def test_branch_switcher_shows_only_own_branches(self):
        self.assertEqual(self.names(self.get(self.admin_a, "/api/v1/branches/")), {"Алмалы"})
        self.assertEqual(self.names(self.get(self.teacher_b, "/api/v1/branches/")), {"Орбита"})
        everyone = {"Алмалы", "Орбита"}
        self.assertEqual(self.names(self.get(self.owner, "/api/v1/branches/")), everyone)
        self.assertEqual(self.names(self.get(self.admin_all, "/api/v1/branches/")), everyone)

    def test_staff_list_shows_colleagues_of_own_branches(self):
        phones = self.names(self.get(self.admin_a, "/api/v1/users/"), "phone")
        self.assertIn(self.admin_a.phone, phones)
        self.assertIn(self.owner.phone, phones)  # без филиалов — работает везде
        self.assertNotIn(self.teacher_b.phone, phones)

    def test_groups_and_children_only_from_own_branch(self):
        self.assertEqual(self.names(self.get(self.admin_a, "/api/v1/groups/")), {"Балет А"})
        children = self.get(self.admin_a, "/api/v1/clients/children/table/")
        self.assertEqual(self.names(children, "full_name"), {"Аня"})

    def test_foreign_branch_in_header_or_param_does_not_open_it(self):
        header = {"HTTP_X_BRANCH_ID": str(self.b.id)}
        self.assertEqual(
            self.names(self.get(self.admin_a, "/api/v1/groups/", **header)), {"Балет А"}
        )
        rows = self.get(self.admin_a, f"/api/v1/groups/?branch={self.b.id}")
        self.assertEqual(self.names(rows), {"Балет А"})

    def test_owner_still_filters_by_header(self):
        header = {"HTTP_X_BRANCH_ID": str(self.b.id)}
        self.assertEqual(self.names(self.get(self.owner, "/api/v1/groups/", **header)), {"Балет Б"})
