"""
GET /api/v1/clients/children/table/ — таблица детей frontend2 (TRU-81).
Логика фильтров/сортировки общая со старой веб-страницей (child_list.py),
поэтому фильтры прогоняются тем же набором тестов, что и веб-эндпоинт
(ChildListFiltersApiTests наследует ChildListFiltersWebViewTests), а здесь —
то, что специфично для API: JWT, активный филиал из X-Branch-Id, скрытие
денег, число запросов.
"""

import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, tag
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from domains.money.subscriptions.sales import sell_subscription
from domains.money.subscriptions.subscription_types import create_type
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.scheduling.groups.models import Group, GroupMembership

from .models import Child
from .tests_child_list import ChildListFiltersWebViewTests

User = get_user_model()
URL = reverse("clients:child-table")


class ChildListFiltersApiTests(ChildListFiltersWebViewTests):
    def setUp(self):
        super().setUp()
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def _get(self, params):
        data = self.api.get(URL, params).json()
        return {"rows": data["results"], "total": data["count"]}


class ChildTableApiTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.owner = User.objects.create_user(
            phone="+77010000001",
            full_name="Owner",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.teacher = User.objects.create_user(
            phone="+77010000002",
            full_name="Teacher",
            password="pass12345",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        self.branch = Branch.objects.create(organization=self.org, name="Центральный")
        self.other_branch = Branch.objects.create(organization=self.org, name="Северный")
        self.direction = Direction.objects.create(organization=self.org, name="Балет")
        self.direction.branches.add(self.branch)
        self.other_direction = Direction.objects.create(organization=self.org, name="Гимнастика")
        self.other_direction.branches.add(self.other_branch)
        self.api = APIClient()

    def _make_child(self, name, direction=None):
        child = Child.objects.create(
            organization=self.org,
            full_name=name,
            birth_date=datetime.date.today() - datetime.timedelta(days=365 * 7),
            gender=Child.Gender.FEMALE,
        )
        if direction:
            child.directions.add(direction)
        return child

    def _sell(self, child, paid_amount):
        if not hasattr(self, "version"):
            sub_type = create_type(
                self.org, name="8 занятий", price=25000, quota_sessions=8, duration_days=30
            )
            self.version = sub_type.versions.latest()
        sell_subscription(
            actor=self.owner,
            child=child,
            subscription_type_version=self.version,
            direction=self.direction,
            branch=self.branch,
            starts_on=datetime.date.today(),
            ends_on=datetime.date.today() + datetime.timedelta(days=30),
            paid_amount=Decimal(paid_amount),
            payment_method="cash",
        )

    def _names(self, response):
        return [row["full_name"] for row in response.json()["results"]]

    def test_anonymous_gets_401(self):
        self.assertEqual(self.api.get(URL).status_code, 401)

    def test_owner_gets_rows_with_money(self):
        child = self._make_child("Аружан", self.direction)
        self._sell(child, 15000)
        self.api.force_authenticate(self.owner)

        data = self.api.get(URL).json()

        self.assertEqual(data["count"], 1)
        self.assertTrue(data["show_money"])
        row = data["results"][0]
        self.assertEqual(row["full_name"], "Аружан")
        self.assertEqual(row["branch_names"], "Центральный")
        self.assertEqual(row["direction_names"], "Балет")
        self.assertEqual(row["subscription_name"], "8 занятий")
        self.assertEqual(Decimal(row["debt"]), Decimal("10000"))

    def test_teacher_gets_no_money_and_money_filters_are_ignored(self):
        child = self._make_child("Должник", self.direction)
        self._sell(child, 0)
        self._make_child("Без долга")
        self.api.force_authenticate(self.teacher)

        data = self.api.get(URL, {"has_debt": "1"}).json()

        self.assertFalse(data["show_money"])
        self.assertEqual(data["count"], 2)
        self.assertTrue(all(row["debt"] is None for row in data["results"]))
        self.assertTrue(all(row["subscription_name"] is None for row in data["results"]))

    def test_active_branch_header_filters_list(self):
        self._make_child("Центр", self.direction)
        self._make_child("Север", self.other_direction)
        self.api.force_authenticate(self.owner)

        response = self.api.get(URL, HTTP_X_BRANCH_ID=str(self.branch.id))

        self.assertEqual(self._names(response), ["Центр"])

    def test_explicit_branch_param_wins_over_header(self):
        self._make_child("Центр", self.direction)
        self._make_child("Север", self.other_direction)
        self.api.force_authenticate(self.owner)

        response = self.api.get(
            URL, {"branch": str(self.other_branch.id)}, HTTP_X_BRANCH_ID=str(self.branch.id)
        )

        self.assertEqual(self._names(response), ["Север"])

    @tag("tenant_isolation")
    def test_foreign_branch_header_is_ignored_and_other_org_hidden(self):
        other_org = Organization.objects.create(name="Other", slug="other")
        foreign_branch = Branch.objects.create(organization=other_org, name="Чужой")
        Child.objects.create(
            organization=other_org,
            full_name="Чужой ребёнок",
            birth_date=datetime.date(2018, 1, 1),
            gender=Child.Gender.FEMALE,
        )
        self._make_child("Свой")
        self.api.force_authenticate(self.owner)

        response = self.api.get(URL, HTTP_X_BRANCH_ID=str(foreign_branch.id))

        self.assertEqual(self._names(response), ["Свой"])

    def test_search_by_name(self):
        self._make_child("Аружан Серикова")
        self._make_child("Милана Ким")
        self.api.force_authenticate(self.owner)

        response = self.api.get(URL, {"q": "аруж"})

        self.assertEqual(self._names(response), ["Аружан Серикова"])

    def test_sort_and_pagination(self):
        for name in ["Вера", "Алина", "Галя", "Белла"]:
            self._make_child(name)
        self.api.force_authenticate(self.owner)

        response = self.api.get(
            URL, {"sort": "full_name", "dir": "desc", "page_size": 2, "page": 2}
        )

        self.assertEqual(self._names(response), ["Белла", "Алина"])
        self.assertEqual(response.json()["count"], 4)

    def test_query_count_does_not_grow_with_rows(self):
        # ТЗ п. 10.2: группа/абонемент/долг — батчем, не запросом на строку.
        group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Группа",
            capacity=30,
        )
        self.api.force_authenticate(self.owner)

        def add_children(start, stop):
            for i in range(start, stop):
                child = self._make_child(f"Ребёнок {i}", self.direction)
                self._sell(child, 1000)
                GroupMembership.objects.create(
                    organization=self.org,
                    group=group,
                    child=child,
                    joined_at=datetime.date.today(),
                )

        def count_queries():
            with CaptureQueriesContext(connection) as ctx:
                response = self.api.get(URL, HTTP_X_BRANCH_ID=str(self.branch.id))
            self.assertEqual(response.status_code, 200)
            return len(ctx.captured_queries)

        add_children(0, 2)
        few = count_queries()
        add_children(2, 12)
        self.assertEqual(count_queries(), few)
