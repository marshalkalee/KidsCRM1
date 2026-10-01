"""
GET /api/v1/clients/children/table/ — таблица детей frontend2 (TRU-81).
Фильтры (ChildListFiltersApiTests) — набор, что раньше стоял на серверной
странице списка (удалена в TRU-88), теперь на API; дальше — то, что
специфично для API: JWT, активный филиал из X-Branch-Id, скрытие денег,
число запросов.
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

User = get_user_model()
URL = reverse("clients:child-table")


class ChildListFiltersApiTests(TestCase):
    """Фильтры списка детей (ТЗ п. 4.1): филиал/направление/группа/статус/
    долг/абонемент, комбинируются между собой. Долг/абонемент — через
    domains.money.subscriptions (debtor_child_ids/expiring_child_ids), не
    свою копию арифметики (см. tests_debt.py/tests_renewals.py там же)."""

    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.owner = User.objects.create_user(
            phone="+77010000001",
            full_name="Owner",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.branch = Branch.objects.create(organization=self.org, name="Центральный")
        self.other_branch = Branch.objects.create(organization=self.org, name="Северный")
        self.direction = Direction.objects.create(organization=self.org, name="Балет")
        self.direction.branches.add(self.branch)
        self.other_direction = Direction.objects.create(organization=self.org, name="Гимнастика")
        self.other_direction.branches.add(self.other_branch)
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def _make_child(self, name, **extra):
        defaults = {
            "organization": self.org,
            "full_name": name,
            "birth_date": datetime.date.today() - datetime.timedelta(days=365 * 7),
            "gender": Child.Gender.FEMALE,
        }
        defaults.update(extra)
        return Child.objects.create(**defaults)

    def _get(self, params):
        data = self.api.get(URL, params).json()
        return {"rows": data["results"], "total": data["count"]}

    def test_filter_by_branch(self):
        in_branch = self._make_child("В филиале")
        in_branch.directions.add(self.direction)
        elsewhere = self._make_child("В другом филиале")
        elsewhere.directions.add(self.other_direction)

        response = self._get({"branch": str(self.branch.id)})

        self.assertEqual([r["full_name"] for r in response["rows"]], ["В филиале"])

    def test_filter_by_direction(self):
        ballet = self._make_child("Балет")
        ballet.directions.add(self.direction)
        gymnastics = self._make_child("Гимнастика")
        gymnastics.directions.add(self.other_direction)

        response = self._get({"direction": str(self.direction.id)})

        self.assertEqual([r["full_name"] for r in response["rows"]], ["Балет"])

    def test_filter_by_group_only_counts_active_membership(self):
        group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Группа А",
            capacity=10,
        )
        current_member = self._make_child("Сейчас в группе")
        GroupMembership.objects.create(
            organization=self.org,
            group=group,
            child=current_member,
            joined_at=datetime.date.today(),
        )
        past_member = self._make_child("Раньше был в группе")
        GroupMembership.objects.create(
            organization=self.org,
            group=group,
            child=past_member,
            joined_at=datetime.date.today() - datetime.timedelta(days=100),
            left_at=datetime.date.today() - datetime.timedelta(days=10),
        )

        response = self._get({"group": str(group.id)})

        self.assertEqual([r["full_name"] for r in response["rows"]], ["Сейчас в группе"])

    def test_filter_by_status(self):
        self._make_child("Активна", status=Child.Status.ACTIVE)
        self._make_child("Ушла", status=Child.Status.LEFT)

        response = self._get({"status": "left"})

        self.assertEqual([r["full_name"] for r in response["rows"]], ["Ушла"])

    def _sell(self, child, paid_amount, **overrides):
        sub_type = overrides.pop(
            "subscription_type",
            create_type(
                self.org, name="8 занятий", price=25000, quota_sessions=8, duration_days=30
            ),
        )
        kwargs = dict(
            actor=self.owner,
            child=child,
            subscription_type_version=sub_type.versions.latest(),
            direction=self.direction,
            branch=Branch.objects.get_or_create(organization=self.org, name="Центральный")[0],
            starts_on=datetime.date.today(),
            paid_amount=paid_amount,
            payment_method="cash",
        )
        kwargs.update(overrides)
        return sell_subscription(**kwargs)

    def test_filter_by_has_debt(self):
        debtor = self._make_child("Должник")
        self._sell(debtor, paid_amount=Decimal("10000"))
        paid_up = self._make_child("Оплатил")
        self._sell(paid_up, paid_amount=Decimal("25000"))

        response = self._get({"has_debt": "1"})

        self.assertEqual([r["full_name"] for r in response["rows"]], ["Должник"])

    def test_filter_by_expiring(self):
        sub_type = create_type(
            self.org, name="8 занятий", price=25000, quota_sessions=8, duration_days=30
        )
        soon = self._make_child("Скоро истекает")
        soon_sub, _payment = sell_subscription(
            actor=self.owner,
            child=soon,
            subscription_type_version=sub_type.versions.latest(),
            direction=self.direction,
            branch=Branch.objects.get_or_create(organization=soon.organization, name="Центральный")[
                0
            ],
            starts_on=datetime.date.today(),
            paid_amount=Decimal("25000"),
            payment_method="cash",
        )
        soon_sub.ends_on = datetime.date.today() + datetime.timedelta(days=2)
        soon_sub.save(update_fields=["ends_on"])

        far = self._make_child("Далеко до конца")
        far_sub, _payment = sell_subscription(
            actor=self.owner,
            child=far,
            subscription_type_version=sub_type.versions.latest(),
            direction=self.direction,
            branch=Branch.objects.get_or_create(organization=far.organization, name="Центральный")[
                0
            ],
            starts_on=datetime.date.today(),
            paid_amount=Decimal("25000"),
            payment_method="cash",
        )
        far_sub.ends_on = datetime.date.today() + datetime.timedelta(days=60)
        far_sub.save(update_fields=["ends_on"])

        response = self._get({"expiring": "1"})

        self.assertEqual([r["full_name"] for r in response["rows"]], ["Скоро истекает"])

    def test_filters_combine_with_and(self):
        # Критерий приёмки: "филиал + направление + есть долг" — только
        # ребёнок, подходящий под ВСЕ три условия одновременно.
        matches_all = self._make_child("Подходит везде")
        matches_all.directions.add(self.direction)
        self._sell(matches_all, paid_amount=Decimal("10000"))

        wrong_branch = self._make_child("Другой филиал, тот же долг")
        wrong_branch.directions.add(self.other_direction)
        self._sell(wrong_branch, paid_amount=Decimal("10000"))

        no_debt = self._make_child("Тот же филиал, оплатил")
        no_debt.directions.add(self.direction)
        self._sell(no_debt, paid_amount=Decimal("25000"))

        response = self._get(
            {
                "branch": str(self.branch.id),
                "direction": str(self.direction.id),
                "has_debt": "1",
            }
        )

        self.assertEqual([r["full_name"] for r in response["rows"]], ["Подходит везде"])

    def test_total_reflects_filtered_count_not_full_list(self):
        matching = self._make_child("Подходит")
        matching.directions.add(self.direction)
        self._make_child("Не подходит")

        response = self._get({"direction": str(self.direction.id)})

        self.assertEqual(response["total"], 1)


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

    def test_branch_comes_from_group_not_from_direction(self):
        # Направление доступно в обоих филиалах, но ребёнок ходит в группу
        # Центрального — там он и числится (TRU-89).
        self.direction.branches.add(self.other_branch)
        in_group = self._make_child("В группе", self.direction)
        group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Младшие",
            capacity=10,
        )
        GroupMembership.objects.create(
            organization=self.org, group=group, child=in_group, joined_at=datetime.date.today()
        )
        self._make_child("Без группы", self.direction)
        self.api.force_authenticate(self.owner)

        rows = {r["full_name"]: r for r in self.api.get(URL).json()["results"]}
        north = self.api.get(URL, {"branch": str(self.other_branch.id)})

        self.assertEqual(rows["В группе"]["branch_names"], "Центральный")
        self.assertEqual(rows["Без группы"]["branch_names"], "Северный, Центральный")
        self.assertEqual(self._names(north), ["Без группы"])

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
