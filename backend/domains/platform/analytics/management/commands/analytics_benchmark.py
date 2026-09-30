"""
Замер аналитики на целевом объёме (TRU-118, ADR-0006). Сначала
`python manage.py seed_analytics`.

    python manage.py analytics_benchmark            # таблица времён
    python manage.py analytics_benchmark --load 4   # + список детей под нагрузкой

Время — без кэша (худший случай: первый заход после истечения кэша).
"""

import statistics
import threading
import time

from django.core.management.base import BaseCommand
from django.db import connection
from rest_framework.test import APIClient

from domains.platform.analytics import metrics  # noqa: F401
from domains.platform.analytics.period import period_for
from domains.platform.analytics.registry import REGISTRY, compute
from domains.platform.analytics.scope import Scope
from domains.platform.core.utils import today_for_org
from domains.platform.tenants.models import Branch, Organization
from domains.platform.users.models import User

from .seed_analytics import SLUG

REPEATS = 3


def _timed(func, repeats=REPEATS):
    runs = []
    for _ in range(repeats):
        started = time.perf_counter()
        func()
        runs.append((time.perf_counter() - started) * 1000)
    return statistics.median(runs)


class Command(BaseCommand):
    help = "Замер метрик аналитики на сиде целевого объёма."

    def add_arguments(self, parser):
        parser.add_argument(
            "--load", type=int, default=0, help="Потоков аналитики для замера под нагрузкой"
        )

    def handle(self, *args, load, **options):
        organization = Organization.objects.get(slug=SLUG)
        today = today_for_org(organization)
        branch = Branch.objects.for_tenant(organization).order_by("name").first()
        scopes = {
            "все филиалы": Scope(organization, None),
            "1 филиал": Scope(organization, (branch.pk,)),
        }
        periods = {
            "месяц": period_for("month", today),
            "год": period_for("custom", today, today.replace(year=today.year - 1), today),
        }

        self.stdout.write(
            f"{'метрика':20} " + " ".join(f"{p + ' / ' + s:>22}" for p in periods for s in scopes)
        )
        for name in REGISTRY:
            cells = []
            for period in periods.values():
                for scope in scopes.values():
                    ms = _timed(
                        lambda n=name, sc=scope, p=period: compute([n], sc, p, use_cache=False)
                    )
                    cells.append(f"{ms:>19.0f} мс")
            self.stdout.write(f"{name:20} " + " ".join(cells))

        names = list(REGISTRY)
        everything = scopes["все филиалы"]
        for label, period in periods.items():
            ms = _timed(lambda p=period: compute(names, everything, p, use_cache=False))
            warm = _timed(lambda p=period: compute(names, everything, p))
            self.stdout.write(
                f"Дашборд целиком ({len(names)} метрик), {label}: "
                f"без кэша {ms:.0f} мс, из кэша {warm:.1f} мс"
            )

        owner = User.objects.get(organization=organization, role=User.Role.OWNER, is_active=True)
        client = APIClient(SERVER_NAME="localhost")
        client.force_authenticate(owner)

        def child_list():
            response = client.get("/api/v1/clients/children/table/", {"page_size": 25})
            assert response.status_code == 200, response.status_code

        baseline = _timed(child_list, repeats=10)
        self.stdout.write(f"Список детей (5000), без нагрузки: {baseline:.0f} мс")
        if load:
            stop = threading.Event()

            def hammer():
                try:
                    while not stop.is_set():
                        compute(names, scopes["все филиалы"], periods["год"], use_cache=False)
                finally:
                    connection.close()

            threads = [threading.Thread(target=hammer) for _ in range(load)]
            for thread in threads:
                thread.start()
            time.sleep(1)
            loaded = _timed(child_list, repeats=10)
            stop.set()
            for thread in threads:
                thread.join()
            self.stdout.write(
                f"Список детей под нагрузкой ({load} потока считают годовой дашборд "
                f"без кэша): {loaded:.0f} мс"
            )
