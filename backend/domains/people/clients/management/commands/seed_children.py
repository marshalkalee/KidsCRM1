"""
Сид данных для замера производительности списка детей (ТЗ п. 10.2:
5000 детей, отклик ≤ 1с — "замерено, а не на глаз"). Не тест сам по себе —
инструмент, чтобы реально нагрузить дев-БД и замерить настоящий ответ
живого сервера, а не только изолированный Django TestCase.

Запуск: python manage.py seed_children --count 5000
"""

import random
import uuid
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from domains.money.payments.models import Payment
from domains.money.subscriptions.models import Subscription, SubscriptionLedgerEntry
from domains.money.subscriptions.subscription_types import create_type
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.scheduling.groups.models import Group, GroupMembership

from ...models import Child

FIRST_NAMES = ["Аружан", "Данияр", "Айгерим", "Ерлан", "Дана", "Санжар", "Асель", "Бекзат"]
LAST_NAMES = ["Ахметова", "Сериков", "Тулегенова", "Нурланов", "Касымова", "Жумабаев"]


class Command(BaseCommand):
    help = (
        "Сидит N детей (+ филиалы/направления/группы/абонементы/оплаты) "
        "для замера производительности списка."
    )

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=5000)
        parser.add_argument(
            "--org-slug",
            default="perf-test-org",
            help=(
                "Слаг тестовой организации — команда создаёт/переиспользует "
                "именно эту, не трогает другие."
            ),
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Удалить существующих детей этой тестовой организации перед сидом.",
        )

    def handle(self, *args, count, org_slug, reset, **options):
        organization, _ = Organization.objects.get_or_create(
            slug=org_slug, defaults={"name": "Perf Test Organization"}
        )

        if reset:
            # QuerySet.delete() — обычный bulk SQL DELETE, не мягкое удаление
            # (то — только у Model.delete() на инстансе): для служебных
            # тестовых данных перфоманс-сида это то, что нужно, иначе при
            # повторных запусках старые дети копились бы бесконечно.
            # Порядок важен — PROTECT на Child со стороны Subscription/
            # GroupMembership/LessonConsumption не даст удалить детей, пока
            # эти строки существуют.
            Payment.objects.for_tenant(organization).delete()
            SubscriptionLedgerEntry.objects.for_tenant(organization).delete()
            Subscription.objects.for_tenant(organization).delete()
            GroupMembership.objects.for_tenant(organization).delete()
            Child.objects.for_tenant(organization).delete()

        branches = [
            Branch.objects.get_or_create(organization=organization, name=f"Филиал {i}")[0]
            for i in range(1, 4)
        ]
        directions = []
        for i, name in enumerate(["Балет", "Дзюдо", "Плавание", "Шахматы"]):
            direction, _ = Direction.objects.get_or_create(organization=organization, name=name)
            direction.branches.set([branches[i % len(branches)]])
            directions.append(direction)

        groups = [
            Group.objects.get_or_create(
                organization=organization,
                branch=branches[i % len(branches)],
                direction=directions[i % len(directions)],
                name=f"Группа {i}",
                defaults={"capacity": 15},
            )[0]
            for i in range(10)
        ]

        subscription_type = create_type(
            organization,
            name="8 занятий",
            price=25000,
            quota_sessions=8,
            duration_days=30,
        )
        subscription_version = subscription_type.versions.latest()

        User = get_user_model()
        author, _ = User.objects.get_or_create(
            phone="+70000000001",
            defaults={
                "full_name": "Perf Test Owner",
                "organization": organization,
                "role": User.Role.OWNER,
            },
        )
        # Всегда переустанавливаем — get_or_create() не хеширует пароль из
        # defaults, свежесозданный пользователь получил бы пустую строку
        # вместо реального хэша (has_usable_password() на пустой строке не
        # надёжный признак "пароль ещё не задан").
        author.set_password("PerfTest123!")
        author.save(update_fields=["password"])

        self.stdout.write(f"Сидим {count} детей в организацию {organization.slug}...")
        with transaction.atomic():
            children = Child.objects.bulk_create(
                [
                    Child(
                        id=uuid.uuid4(),
                        organization=organization,
                        full_name=f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}",
                        birth_date=date.today() - timedelta(days=365 * random.randint(3, 15)),
                        gender=random.choice(["male", "female"]),
                        status=random.choices(["active", "paused", "left"], weights=[80, 15, 5])[0],
                    )
                    for _ in range(count)
                ]
            )

            # Направления — не у всех (реалистично: не каждый ребёнок уже
            # записан хоть куда-то), группы/абонементы — у меньшей части,
            # достаточно для проверки, что батч-запросы реально работают
            # на непустых данных, не для повторения полного объёма.
            direction_through = Child.directions.through
            direction_through.objects.bulk_create(
                [
                    direction_through(child_id=child.id, direction_id=random.choice(directions).id)
                    for child in children
                    if random.random() < 0.7
                ]
            )

            with_group = [c for c in children if random.random() < 0.4]
            GroupMembership.objects.bulk_create(
                [
                    GroupMembership(
                        id=uuid.uuid4(),
                        organization=organization,
                        group=random.choice(groups),
                        child=child,
                        joined_at=date.today() - timedelta(days=random.randint(1, 200)),
                    )
                    for child in with_group
                ]
            )

            with_subscription = [c for c in children if random.random() < 0.5]
            subscriptions = Subscription.objects.bulk_create(
                [
                    Subscription(
                        id=uuid.uuid4(),
                        organization=organization,
                        child=child,
                        subscription_type_version=subscription_version,
                        direction=random.choice(directions),
                        starts_on=date.today() - timedelta(days=10),
                        ends_on=date.today() + timedelta(days=20),
                        list_price=25000,
                        price=25000,
                    )
                    for child in with_subscription
                ]
            )
            if author is not None:
                SubscriptionLedgerEntry.objects.bulk_create(
                    [
                        SubscriptionLedgerEntry(
                            id=uuid.uuid4(),
                            organization=organization,
                            subscription=sub,
                            kind=SubscriptionLedgerEntry.Kind.INITIAL_GRANT,
                            delta=8,
                        )
                        for sub in subscriptions
                    ]
                )
                # Часть оплачена полностью, часть частично — реальная долговая
                # картина, не все нули и не все "оплачено".
                Payment.objects.bulk_create(
                    [
                        Payment(
                            id=uuid.uuid4(),
                            organization=organization,
                            subscription=sub,
                            amount=random.choice([25000, 15000, 10000, 0]),
                            method="cash",
                            received_by=author,
                        )
                        for sub in subscriptions
                        if random.random() < 0.8
                    ]
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Готово: {Child.objects.for_tenant(organization).count()} детей в организации "
                f"{organization.slug} (id={organization.id})."
            )
        )
