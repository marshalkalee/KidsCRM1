"""Пиковая минута детского центра (TRU-155, ТЗ п. 10.2).

Профиль намеренно ограничен четырьмя пользовательскими действиями из ТЗ:
список детей, недельный календарь, журнал посещаемости и приём оплаты.
Подготовительные идентификаторы берутся напрямую из изолированной load-test
организации и не попадают в HTTP-статистику.
"""

import os
import random
import uuid
from datetime import timedelta

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

import django  # noqa: E402

django.setup()

from django.utils import timezone  # noqa: E402
from locust import HttpUser, between, task  # noqa: E402
from rest_framework_simplejwt.tokens import RefreshToken  # noqa: E402

from domains.money.subscriptions.models import Subscription  # noqa: E402
from domains.platform.analytics.management.commands.seed_analytics import SLUG  # noqa: E402
from domains.platform.tenants.models import Organization  # noqa: E402
from domains.platform.users.models import User  # noqa: E402
from domains.scheduling.schedule.models import Lesson  # noqa: E402


def _target():
    organization = Organization.objects.get(slug=SLUG)
    owner = User.objects.get(organization=organization, role=User.Role.OWNER, is_active=True)
    lesson_ids = list(
        Lesson.objects.for_tenant(organization)
        .filter(group__isnull=False)
        .order_by("-starts_at")
        .values_list("id", flat=True)[:100]
    )
    subscription_ids = list(
        Subscription.objects.for_tenant(organization)
        .order_by("-starts_on")
        .values_list("id", flat=True)[:500]
    )
    if not lesson_ids or not subscription_ids:
        raise RuntimeError("Сначала выполните seed_analytics для целевого объёма.")
    refresh = RefreshToken.for_user(owner)
    refresh["organization_id"] = str(organization.id)
    refresh["role"] = owner.role
    access = str(refresh.access_token)
    today = timezone.localdate()
    return {
        "token": access,
        "lessons": [str(value) for value in lesson_ids],
        "subscriptions": [str(value) for value in subscription_ids],
        "date_from": (today - timedelta(days=6)).isoformat(),
        "date_to": today.isoformat(),
    }


TARGET = _target()


class PeakMinuteUser(HttpUser):
    """20 таких пользователей моделируют одновременную работу центра."""

    # Реальный сотрудник читает открытый экран перед следующим действием.
    # Субсекундная пауза превращает профиль в синтетический RPS-тест, который
    # TRU-155 прямо исключает, и не моделирует 20 работающих устройств.
    wait_time = between(2, 5)

    def on_start(self):
        self.client.headers.update(
            {
                "Authorization": f"Bearer {TARGET['token']}",
                # Внутреннее DNS-имя compose — nginx, но Django намеренно
                # принимает публичный host приложения, а не имена сети.
                "Host": "localhost",
            }
        )

    @task(4)
    def attendance_roster(self):
        lesson_id = random.choice(TARGET["lessons"])
        with self.client.get(
            "/api/v1/attendance/roster/",
            params={"lesson": lesson_id},
            name="01 attendance roster",
            catch_response=True,
        ) as response:
            self._expect(response, 200)

    @task(3)
    def weekly_calendar(self):
        with self.client.get(
            "/api/v1/schedule/",
            params={"date_from": TARGET["date_from"], "date_to": TARGET["date_to"]},
            name="02 weekly calendar",
            catch_response=True,
        ) as response:
            self._expect(response, 200)

    @task(3)
    def children_table(self):
        with self.client.get(
            "/api/v1/clients/children/table/",
            params={"page": 1, "page_size": 25},
            name="03 children table",
            catch_response=True,
        ) as response:
            self._expect(response, 200)

    @task(1)
    def accept_payment(self):
        with self.client.post(
            "/api/v1/payments/",
            json={
                "subscription": random.choice(TARGET["subscriptions"]),
                "amount": "1",
                "method": "cash",
                "idempotency_key": str(uuid.uuid4()),
                "comment": "TRU-155 load test",
            },
            name="04 accept payment",
            catch_response=True,
        ) as response:
            self._expect(response, 201)

    @staticmethod
    def _expect(response, expected):
        if response.status_code == expected:
            response.success()
        else:
            response.failure(f"HTTP {response.status_code}: {response.text[:200]}")
