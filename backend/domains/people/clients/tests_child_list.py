"""
Веб-экраны "Дети" и "Родители" (список + создание/редактирование, серверный
рендеринг). Не отдельный тикет — фронт для того, что раньше было
API-only (тикеты "Ребёнок"/"Родитель и контактное лицо"), сделан по образцу
Направлений (список + AJAX-модалки создания/редактирования).
"""

import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from domains.money.subscriptions.sales import sell_subscription
from domains.money.subscriptions.subscription_types import create_type
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.scheduling.groups.models import Group, GroupMembership

from .models import Child, ContactPhone, ParentContact

User = get_user_model()


class ChildListWebViewTests(TestCase):
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

    def test_owner_sees_child_list_page_shell(self):
        # Каркас страницы — сами строки грузит child-list-data (удалённый
        # режим table.js, см. ChildListDataWebViewTests), в HTML их больше
        # нет ни в каком виде (ни текстом, ни json_script).
        self.client.force_login(self.owner)

        response = self.client.get(reverse("clients_web:child-list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="js-children-table"')

    def test_teacher_can_view_list_but_no_create_button(self):
        self.client.force_login(self.teacher)

        response = self.client.get(reverse("clients_web:child-list"))

        self.assertEqual(response.status_code, 200)
        # id="js-create-child" — сам элемент кнопки; JS-код, который на
        # неё ссылается (getElementById), в разметке есть всегда.
        self.assertNotIn(b'id="js-create-child"', response.content)

    def test_owner_creates_child_via_web_form(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("clients_web:child-create"),
            {
                "full_name": "Данияр",
                "birth_date": "2018-05-01",
                "gender": "male",
                "status": "active",
            },
        )

        self.assertEqual(response.status_code, 302)
        child = Child.objects.get(full_name="Данияр")
        self.assertEqual(child.organization, self.org)

    def test_teacher_cannot_create_child(self):
        self.client.force_login(self.teacher)

        response = self.client.get(reverse("clients_web:child-create"))

        self.assertEqual(response.status_code, 403)

    def test_birth_date_in_future_is_rejected_via_web_form(self):
        self.client.force_login(self.owner)
        future_date = str(datetime.date.today() + datetime.timedelta(days=1))

        response = self.client.post(
            reverse("clients_web:child-create"),
            {
                "full_name": "Данияр",
                "birth_date": future_date,
                "gender": "male",
                "status": "active",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Child.objects.filter(full_name="Данияр").exists())


class ChildListDataWebViewTests(TestCase):
    """child-list-data — удалённый режим table.js (ТЗ п. 10.2): страница,
    сортировка и колонки филиал/направление/группа/абонемент/долг батчем,
    не запросом на строку. См. также tests_child_list_performance.py —
    там же самый эндпоинт, но замер на реалистичном объёме."""

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

    def _make_child(self, name, age_years=7, **extra):
        defaults = {
            "organization": self.org,
            "full_name": name,
            "birth_date": datetime.date.today() - datetime.timedelta(days=365 * age_years),
            "gender": Child.Gender.FEMALE,
        }
        defaults.update(extra)
        return Child.objects.create(**defaults)

    def test_returns_json_with_rows_and_total(self):
        self._make_child("Аружан")
        self.client.force_login(self.owner)

        response = self.client.get(reverse("clients_web:child-list-data"))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["rows"][0]["full_name"], "Аружан")

    def test_teacher_can_view_data(self):
        self._make_child("Аружан")
        self.client.force_login(self.teacher)

        response = self.client.get(reverse("clients_web:child-list-data"))

        self.assertEqual(response.status_code, 200)

    def test_pagination_splits_across_pages(self):
        for i in range(5):
            self._make_child(f"Ребёнок {i}")
        self.client.force_login(self.owner)

        page1 = self.client.get(
            reverse("clients_web:child-list-data"), {"page": 1, "page_size": 2}
        ).json()
        page2 = self.client.get(
            reverse("clients_web:child-list-data"), {"page": 2, "page_size": 2}
        ).json()

        self.assertEqual(page1["total"], 5)
        self.assertEqual(len(page1["rows"]), 2)
        self.assertEqual(len(page2["rows"]), 2)
        self.assertNotEqual({r["id"] for r in page1["rows"]}, {r["id"] for r in page2["rows"]})

    def test_page_size_is_capped(self):
        # С фронта нельзя запросить page_size=5000 и вернуться к "отдать
        # всё разом" — верхняя граница на сервере, не только по умолчанию.
        for i in range(3):
            self._make_child(f"Ребёнок {i}")
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("clients_web:child-list-data"), {"page_size": 100000}
        ).json()

        self.assertLessEqual(len(response["rows"]), 200)

    def test_sort_by_full_name_descending(self):
        self._make_child("Аружан")
        self._make_child("Бекзат")
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("clients_web:child-list-data"), {"sort": "full_name", "dir": "desc"}
        ).json()

        self.assertEqual([r["full_name"] for r in response["rows"]], ["Бекзат", "Аружан"])

    def test_sort_by_age_ascending_is_youngest_first(self):
        older = self._make_child("Старший", age_years=10)
        younger = self._make_child("Младший", age_years=5)
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("clients_web:child-list-data"), {"sort": "age", "dir": "asc"}
        ).json()

        self.assertEqual([r["id"] for r in response["rows"]], [str(younger.id), str(older.id)])

    def test_sort_by_status(self):
        self._make_child("Активна", status=Child.Status.ACTIVE)
        self._make_child("Ушла", status=Child.Status.LEFT)
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("clients_web:child-list-data"), {"sort": "status", "dir": "asc"}
        ).json()

        # "active" < "left" лексикографически — просто фиксируем реальный
        # порядок ASC, не гадаем его на глаз.
        statuses = [r["status"] for r in response["rows"]]
        self.assertEqual(statuses, sorted(statuses))

    def test_branch_and_direction_columns_are_populated(self):
        branch = Branch.objects.create(organization=self.org, name="Центральный")
        direction = Direction.objects.create(organization=self.org, name="Балет")
        direction.branches.add(branch)
        child = self._make_child("Аружан")
        child.directions.add(direction)
        self.client.force_login(self.owner)

        response = self.client.get(reverse("clients_web:child-list-data")).json()

        row = response["rows"][0]
        self.assertEqual(row["branch_names"], "Центральный")
        self.assertEqual(row["direction_names"], "Балет")

    def test_group_column_shows_only_active_membership(self):
        child = self._make_child("Аружан")
        branch = Branch.objects.create(organization=self.org, name="Центральный")
        direction = Direction.objects.create(organization=self.org, name="Балет")
        active_group = Group.objects.create(
            organization=self.org, branch=branch, direction=direction, name="Группа А", capacity=10
        )
        past_group = Group.objects.create(
            organization=self.org, branch=branch, direction=direction, name="Группа Б", capacity=10
        )
        GroupMembership.objects.create(
            organization=self.org, group=active_group, child=child, joined_at=datetime.date.today()
        )
        GroupMembership.objects.create(
            organization=self.org,
            group=past_group,
            child=child,
            joined_at=datetime.date.today() - datetime.timedelta(days=100),
            left_at=datetime.date.today() - datetime.timedelta(days=10),
        )
        self.client.force_login(self.owner)

        response = self.client.get(reverse("clients_web:child-list-data")).json()

        self.assertEqual(response["rows"][0]["group_names"], "Группа А")

    def test_subscription_and_debt_columns(self):
        child = self._make_child("Аружан")
        direction = Direction.objects.create(organization=self.org, name="Балет")
        sub_type = create_type(
            self.org, name="8 занятий", price=25000, quota_sessions=8, duration_days=30
        )
        version = sub_type.versions.latest()
        sell_subscription(
            actor=self.owner,
            child=child,
            subscription_type_version=version,
            direction=direction,
            starts_on=datetime.date.today(),
            ends_on=datetime.date.today() + datetime.timedelta(days=30),
            paid_amount=Decimal("15000"),
            payment_method="cash",
        )
        self.client.force_login(self.owner)

        response = self.client.get(reverse("clients_web:child-list-data")).json()

        row = response["rows"][0]
        self.assertEqual(row["subscription_name"], "8 занятий")
        self.assertEqual(Decimal(row["debt"]), Decimal("10000"))

    def test_teacher_gets_no_money_columns_and_no_money_filters(self):
        child = self._make_child("Аружан")
        direction = Direction.objects.create(organization=self.org, name="Балет")
        sub_type = create_type(
            self.org, name="8 занятий", price=25000, quota_sessions=8, duration_days=30
        )
        sell_subscription(
            actor=self.owner,
            child=child,
            subscription_type_version=sub_type.versions.latest(),
            direction=direction,
            starts_on=datetime.date.today(),
            ends_on=datetime.date.today() + datetime.timedelta(days=30),
            paid_amount=Decimal("15000"),
            payment_method="cash",
        )
        teacher = User.objects.create_user(
            phone="+77010000009",
            full_name="Teacher",
            password="pass12345",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        self._make_child("Без долга")
        self.client.force_login(teacher)

        response = self.client.get(reverse("clients_web:child-list-data"), {"has_debt": "1"}).json()

        # Фильтр по долгу для преподавателя игнорируется — видны оба ребёнка.
        self.assertEqual(response["total"], 2)
        self.assertTrue(all(row["debt"] is None for row in response["rows"]))
        self.assertTrue(all(row["subscription_name"] is None for row in response["rows"]))

    def test_fully_paid_subscription_has_zero_debt(self):
        child = self._make_child("Аружан")
        direction = Direction.objects.create(organization=self.org, name="Балет")
        sub_type = create_type(
            self.org, name="8 занятий", price=25000, quota_sessions=8, duration_days=30
        )
        version = sub_type.versions.latest()
        sell_subscription(
            actor=self.owner,
            child=child,
            subscription_type_version=version,
            direction=direction,
            starts_on=datetime.date.today(),
            ends_on=datetime.date.today() + datetime.timedelta(days=30),
            paid_amount=Decimal("25000"),
            payment_method="cash",
        )
        self.client.force_login(self.owner)

        response = self.client.get(reverse("clients_web:child-list-data")).json()

        self.assertEqual(Decimal(response["rows"][0]["debt"]), Decimal("0"))

    def test_does_not_leak_other_organizations_children(self):
        other_org = Organization.objects.create(name="Другая студия", slug="another-studio")
        Child.objects.create(
            organization=other_org,
            full_name="Чужой",
            birth_date=datetime.date.today() - datetime.timedelta(days=365 * 7),
            gender=Child.Gender.FEMALE,
        )
        self._make_child("Аружан")
        self.client.force_login(self.owner)

        response = self.client.get(reverse("clients_web:child-list-data")).json()

        self.assertEqual(response["total"], 1)
        self.assertEqual(response["rows"][0]["full_name"], "Аружан")

    def test_query_count_does_not_grow_with_page_size(self):
        # Критерий приёмки: "нет запроса на строку". Число запросов должно
        # быть константой независимо от того, 1 ребёнок на странице или 50 —
        # иначе бюджет ≤1с на 5000 детей не выдержать (ТЗ п. 10.2).
        direction = Direction.objects.create(organization=self.org, name="Балет")
        branch = Branch.objects.create(organization=self.org, name="Центральный")
        direction.branches.add(branch)
        sub_type = create_type(
            self.org, name="8 занятий", price=25000, quota_sessions=8, duration_days=30
        )
        version = sub_type.versions.latest()
        group = Group.objects.create(
            organization=self.org, branch=branch, direction=direction, name="Группа А", capacity=10
        )

        for i in range(3):
            child = self._make_child(f"Ребёнок {i}")
            child.directions.add(direction)
            GroupMembership.objects.create(
                organization=self.org, group=group, child=child, joined_at=datetime.date.today()
            )
            sell_subscription(
                actor=self.owner,
                child=child,
                subscription_type_version=version,
                direction=direction,
                starts_on=datetime.date.today(),
                ends_on=datetime.date.today() + datetime.timedelta(days=30),
                paid_amount=Decimal("10000"),
                payment_method="cash",
            )
        self.client.force_login(self.owner)

        with self.assertNumQueries(10):
            response = self.client.get(
                reverse("clients_web:child-list-data"), {"page_size": 1}
            ).json()
        self.assertEqual(len(response["rows"]), 1)

        with self.assertNumQueries(10):
            response = self.client.get(
                reverse("clients_web:child-list-data"), {"page_size": 3}
            ).json()
        self.assertEqual(len(response["rows"]), 3)


class ChildListFiltersWebViewTests(TestCase):
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
        self.client.force_login(self.owner)

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
        return self.client.get(reverse("clients_web:child-list-data"), params).json()

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
            starts_on=datetime.date.today(),
            ends_on=datetime.date.today() + datetime.timedelta(days=30),
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
        sell_subscription(
            actor=self.owner,
            child=soon,
            subscription_type_version=sub_type.versions.latest(),
            direction=self.direction,
            starts_on=datetime.date.today(),
            ends_on=datetime.date.today() + datetime.timedelta(days=2),
            paid_amount=Decimal("25000"),
            payment_method="cash",
        )
        far = self._make_child("Далеко до конца")
        sell_subscription(
            actor=self.owner,
            child=far,
            subscription_type_version=sub_type.versions.latest(),
            direction=self.direction,
            starts_on=datetime.date.today(),
            ends_on=datetime.date.today() + datetime.timedelta(days=60),
            paid_amount=Decimal("25000"),
            payment_method="cash",
        )

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


class ParentListWebViewTests(TestCase):
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

    def test_owner_sees_parent_list_with_phone(self):
        parent = ParentContact.objects.create(organization=self.org, full_name="Мама Тестова")
        ContactPhone.objects.create(
            organization=self.org, parent_contact=parent, number="+77011234567"
        )
        self.client.force_login(self.owner)

        response = self.client.get(reverse("clients_web:parent-list"))

        self.assertEqual(response.status_code, 200)
        # Список рендерится на клиенте из json_script — кириллица там
        # экранирована (\uXXXX), поэтому проверяем id, а телефон (ASCII)
        # проверяем как литеральный текст.
        self.assertContains(response, str(parent.id))
        self.assertContains(response, "+77011234567")

    def test_teacher_does_not_see_phone_in_list(self):
        parent = ParentContact.objects.create(organization=self.org, full_name="Мама Тестова")
        ContactPhone.objects.create(
            organization=self.org, parent_contact=parent, number="+77011234567"
        )
        self.client.force_login(self.teacher)

        response = self.client.get(reverse("clients_web:parent-list"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "+77011234567")

    def test_owner_creates_parent_with_two_phones_via_formset(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("clients_web:parent-create"),
            {
                "full_name": "Айгуль",
                "whatsapp": "",
                "email": "",
                "phones-TOTAL_FORMS": "2",
                "phones-INITIAL_FORMS": "0",
                "phones-MIN_NUM_FORMS": "1",
                "phones-MAX_NUM_FORMS": "1000",
                "phones-0-number": "+7 701 123-45-67",
                "phones-0-phone_type": "mobile",
                "phones-1-number": "8 (727) 222-33-44",
                "phones-1-phone_type": "work",
            },
        )

        self.assertEqual(response.status_code, 302, response.content)
        parent = ParentContact.objects.get(full_name="Айгуль")
        numbers = sorted(parent.phones.values_list("number", flat=True))
        self.assertEqual(numbers, ["+77011234567", "+77272223344"])

    def test_creating_parent_without_phones_is_rejected(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("clients_web:parent-create"),
            {
                "full_name": "Айгуль",
                "whatsapp": "",
                "email": "",
                "phones-TOTAL_FORMS": "1",
                "phones-INITIAL_FORMS": "0",
                "phones-MIN_NUM_FORMS": "1",
                "phones-MAX_NUM_FORMS": "1000",
                "phones-0-number": "",
                "phones-0-phone_type": "mobile",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(ParentContact.objects.filter(full_name="Айгуль").exists())

    def test_editing_parent_replaces_phone_via_formset(self):
        parent = ParentContact.objects.create(organization=self.org, full_name="Айгуль")
        old_phone = ContactPhone.objects.create(
            organization=self.org, parent_contact=parent, number="+77011234567"
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("clients_web:parent-edit", args=[parent.pk]),
            {
                "full_name": "Айгуль",
                "whatsapp": "",
                "email": "",
                "phones-TOTAL_FORMS": "1",
                "phones-INITIAL_FORMS": "1",
                "phones-MIN_NUM_FORMS": "1",
                "phones-MAX_NUM_FORMS": "1000",
                "phones-0-id": str(old_phone.pk),
                "phones-0-number": "+77019999999",
                "phones-0-phone_type": "mobile",
            },
        )

        self.assertEqual(response.status_code, 302, response.content)
        old_phone.refresh_from_db()
        self.assertEqual(old_phone.number, "+77019999999")

    def test_deleting_phone_via_formset_is_soft_delete(self):
        parent = ParentContact.objects.create(organization=self.org, full_name="Айгуль")
        first_phone = ContactPhone.objects.create(
            organization=self.org, parent_contact=parent, number="+77011234567"
        )
        second_phone = ContactPhone.objects.create(
            organization=self.org, parent_contact=parent, number="+77019999999"
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("clients_web:parent-edit", args=[parent.pk]),
            {
                "full_name": "Айгуль",
                "whatsapp": "",
                "email": "",
                "phones-TOTAL_FORMS": "2",
                "phones-INITIAL_FORMS": "2",
                "phones-MIN_NUM_FORMS": "1",
                "phones-MAX_NUM_FORMS": "1000",
                "phones-0-id": str(first_phone.pk),
                "phones-0-number": "+77011234567",
                "phones-0-phone_type": "mobile",
                "phones-0-DELETE": "on",
                "phones-1-id": str(second_phone.pk),
                "phones-1-number": "+77019999999",
                "phones-1-phone_type": "mobile",
            },
        )

        self.assertEqual(response.status_code, 302, response.content)
        self.assertFalse(ContactPhone.objects.filter(pk=first_phone.pk).exists())
        # Мягкое удаление — строка физически на месте, просто скрыта менеджером.
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT deleted_at FROM clients_contactphone WHERE id = %s", [str(first_phone.pk)]
            )
            row = cursor.fetchone()
        self.assertIsNotNone(row[0])

    def test_owner_deletes_parent(self):
        parent = ParentContact.objects.create(organization=self.org, full_name="Айгуль")
        self.client.force_login(self.owner)

        response = self.client.post(reverse("clients_web:parent-delete", args=[parent.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(ParentContact.objects.filter(pk=parent.pk).exists())

    def test_teacher_cannot_delete_parent(self):
        parent = ParentContact.objects.create(organization=self.org, full_name="Айгуль")
        self.client.force_login(self.teacher)

        response = self.client.post(reverse("clients_web:parent-delete", args=[parent.pk]))

        self.assertEqual(response.status_code, 403)


class ChildParentTenantIsolationWebTests(TestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.org_b = Organization.objects.create(name="Другая студия", slug="another-studio")
        self.direction_b = Direction.objects.create(organization=self.org_b, name="Балет Б")
        self.owner_a = User.objects.create_user(
            phone="+77010000001",
            full_name="Owner A",
            password="pass12345",
            organization=self.org_a,
            role=User.Role.OWNER,
        )
        self.child_b = Child.objects.create(
            organization=self.org_b,
            full_name="Чужой ребёнок",
            birth_date=datetime.date.today() - datetime.timedelta(days=365 * 6),
            gender=Child.Gender.MALE,
        )
        self.parent_b = ParentContact.objects.create(
            organization=self.org_b, full_name="Чужая мама"
        )
        self.client.force_login(self.owner_a)

    def test_child_list_does_not_leak_other_organizations_children(self):
        response = self.client.get(reverse("clients_web:child-list"))

        self.assertNotContains(response, "Чужой ребёнок")

    def test_cannot_edit_another_organizations_child(self):
        response = self.client.get(reverse("clients_web:child-edit", args=[self.child_b.pk]))

        self.assertEqual(response.status_code, 404)

    def test_parent_list_does_not_leak_other_organizations_parents(self):
        response = self.client.get(reverse("clients_web:parent-list"))

        self.assertNotContains(response, "Чужая мама")

    def test_cannot_edit_another_organizations_parent(self):
        response = self.client.get(reverse("clients_web:parent-edit", args=[self.parent_b.pk]))

        self.assertEqual(response.status_code, 404)

    def test_cannot_delete_another_organizations_parent(self):
        response = self.client.post(reverse("clients_web:parent-delete", args=[self.parent_b.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(ParentContact.objects.filter(pk=self.parent_b.pk).exists())
