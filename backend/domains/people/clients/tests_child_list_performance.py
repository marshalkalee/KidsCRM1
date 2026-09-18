"""
ТЗ п. 10.2: список детей — 5000 детей в организации, отклик ≤ 1с,
"замерено, а не на глаз". Этот тест — постоянный регрессионный барьер в
CI (реальный замер, не ручной); ручной замер на живом деве — через
management-команду seed_children (см. её docstring) плюс curl/браузер.

bulk_create(), не Child.objects.create() в цикле — иначе сама подготовка
теста стала бы медленнее собственного бюджета, который она проверяет.
"""

import random
import time
import uuid
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, tag
from django.urls import reverse

from domains.money.payments.models import Payment
from domains.money.subscriptions.models import Subscription
from domains.money.subscriptions.subscription_types import create_type
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.scheduling.groups.models import Group, GroupMembership

from .models import Child

User = get_user_model()

CHILD_COUNT = 5000
# Реальный бюджет из ТЗ — 1с. В CI/дев-контейнере (не прод-железо) даём
# запас, иначе тест был бы шумным от посторонних факторов среды, но
# граница всё равно на порядок жёстче, чем "просто не зависло".
RESPONSE_BUDGET_SECONDS = 2.5


@tag("performance")
class ChildListPerformanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Perf Ballet", slug="perf-ballet")
        cls.owner = User.objects.create_user(
            phone="+77010000099",
            full_name="Owner",
            password="pass12345",
            organization=cls.org,
            role=User.Role.OWNER,
        )

        branch = Branch.objects.create(organization=cls.org, name="Филиал 1")
        direction = Direction.objects.create(organization=cls.org, name="Балет")
        direction.branches.add(branch)
        group = Group.objects.create(
            organization=cls.org, branch=branch, direction=direction, name="Группа 1", capacity=15
        )
        sub_type = create_type(
            cls.org, name="8 занятий", price=25000, quota_sessions=8, duration_days=30
        )
        version = sub_type.versions.latest()

        children = Child.objects.bulk_create(
            [
                Child(
                    id=uuid.uuid4(),
                    organization=cls.org,
                    full_name=f"Ребёнок {i}",
                    birth_date=date.today() - timedelta(days=365 * random.randint(3, 15)),
                    gender="female",
                    status=random.choices(["active", "paused", "left"], weights=[80, 15, 5])[0],
                )
                for i in range(CHILD_COUNT)
            ]
        )

        direction_through = Child.directions.through
        direction_through.objects.bulk_create(
            [
                direction_through(child_id=child.id, direction_id=direction.id)
                for child in children
                if random.random() < 0.7
            ]
        )
        GroupMembership.objects.bulk_create(
            [
                GroupMembership(
                    id=uuid.uuid4(),
                    organization=cls.org,
                    group=group,
                    child=child,
                    joined_at=date.today(),
                )
                for child in children
                if random.random() < 0.4
            ]
        )
        subscriptions = Subscription.objects.bulk_create(
            [
                Subscription(
                    id=uuid.uuid4(),
                    organization=cls.org,
                    child=child,
                    subscription_type_version=version,
                    direction=direction,
                    starts_on=date.today() - timedelta(days=10),
                    ends_on=date.today() + timedelta(days=20),
                    list_price=25000,
                    price=25000,
                )
                for child in children
                if random.random() < 0.5
            ]
        )
        Payment.objects.bulk_create(
            [
                Payment(
                    id=uuid.uuid4(),
                    organization=cls.org,
                    subscription=sub,
                    amount=random.choice([25000, 15000, 0]),
                    method="cash",
                    received_by=cls.owner,
                )
                for sub in subscriptions
                if random.random() < 0.8
            ]
        )

    def setUp(self):
        self.client.force_login(self.owner)

    def test_first_page_responds_within_budget(self):
        start = time.perf_counter()
        response = self.client.get(
            reverse("clients_web:child-list-data"), {"page": 1, "page_size": 50}
        )
        elapsed = time.perf_counter() - start

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], CHILD_COUNT)
        self.assertLess(
            elapsed,
            RESPONSE_BUDGET_SECONDS,
            f"child-list-data ответил за {elapsed:.3f}с на {CHILD_COUNT} детей "
            f"(бюджет теста {RESPONSE_BUDGET_SECONDS}с, целевой бюджет ТЗ п. 10.2 — 1с)",
        )

    def test_sorted_last_page_responds_within_budget(self):
        # Худший реалистичный случай — сортировка + офсет в конец списка
        # (не просто первая страница с "тёплым" индексом в начале).
        last_page = CHILD_COUNT // 50
        start = time.perf_counter()
        response = self.client.get(
            reverse("clients_web:child-list-data"),
            {"page": last_page, "page_size": 50, "sort": "full_name", "dir": "desc"},
        )
        elapsed = time.perf_counter() - start

        self.assertEqual(response.status_code, 200)
        self.assertLess(
            elapsed,
            RESPONSE_BUDGET_SECONDS,
            f"последняя страница с сортировкой ответила за {elapsed:.3f}с "
            f"(бюджет теста {RESPONSE_BUDGET_SECONDS}с)",
        )

    def test_query_count_is_constant_regardless_of_dataset_size(self):
        # Критерий приёмки "нет запроса на строку" — тот же самый эндпоинт,
        # что и в tests_child_list.py, здесь просто на реалистичном объёме
        # (5000), чтобы явно связать это утверждение с самим ТЗ п. 10.2.
        with self.assertNumQueries(10):
            self.client.get(reverse("clients_web:child-list-data"), {"page_size": 50})
