"""Преобразовать Locust CSV в воспроизводимый Markdown-отчёт."""

import csv
import os
from datetime import UTC, datetime
from pathlib import Path

import django
from django.db import connection

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
django.setup()

from domains.people.clients.models import Child  # noqa: E402
from domains.platform.analytics.management.commands.seed_analytics import SLUG  # noqa: E402
from domains.platform.tenants.models import Organization  # noqa: E402
from domains.platform.users.models import User  # noqa: E402
from domains.scheduling.schedule.models import Lesson  # noqa: E402

SCREENS = {
    "01 attendance roster": "Отметка посещаемости",
    "02 weekly calendar": "Календарь на неделю",
    "03 children table": "Список детей",
    "04 accept payment": "Приём оплаты",
}


def _read(prefix):
    path = Path(f"{prefix}_stats.csv")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return {row["Name"]: row for row in csv.DictReader(stream) if row["Name"] in SCREENS}


def write_report(prefixes, output, *, users, duration, labels=None):
    organization = Organization.objects.get(slug=SLUG)
    labels = labels or [Path(prefix).name for prefix in prefixes]
    with connection.cursor() as cursor:
        cursor.execute("SHOW random_page_cost")
        current_cost = cursor.fetchone()[0]
    scale = {
        "organizations": Organization.objects.count(),
        "total_children": Child.objects.count(),
        "children": Child.objects.for_tenant(organization).count(),
        "staff": User.objects.filter(organization=organization).count(),
        "lessons": Lesson.objects.for_tenant(organization).count(),
    }
    lines = [
        "# TRU-155 — нагрузочное тестирование",
        "",
        f"Сформировано: {datetime.now(UTC).isoformat(timespec='seconds')}.",
        "",
        "## Профиль",
        "",
        f"- Одновременных пользователей: **{users}**.",
        f"- Длительность каждого прогона: **{duration}**.",
        f"- Организаций в БД: **{scale['organizations']}**.",
        f"- Целевой тенант: **{scale['children']} детей, {scale['staff']} сотрудников, "
        f"{scale['lessons']} занятий за год**.",
        f"- Текущее глобальное `random_page_cost`: **{current_cost}**.",
        "- Бюджет ТЗ: **p95 ≤ 1000 мс** для каждого экрана.",
        "",
        "Locust создаёт реальные оплаты по 1 ₸ в изолированной нагрузочной организации. "
        "Повторный запуск требует `--seed`, если нужен полностью чистый набор оплат.",
        "",
    ]
    all_results = []
    for prefix, label in zip(prefixes, labels, strict=True):
        rows = _read(prefix)
        all_results.append((label, rows))
        lines.extend(
            [
                f"## Результат: {label}",
                "",
                "| Экран | Запросов | Ошибок | p50, мс | p95, мс | Бюджет |",
                "| --- | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for key, title in SCREENS.items():
            row = rows.get(key)
            if not row:
                lines.append(f"| {title} | — | — | — | — | нет данных |")
                continue
            p50 = float(row.get("50%") or row.get("Median Response Time") or 0)
            p95 = float(row.get("95%") or 0)
            failures = int(row["Failure Count"])
            verdict = "✅" if p95 <= 1000 and failures == 0 else "❌ требует разбора"
            lines.append(
                f"| {title} | {row['Request Count']} | {row['Failure Count']} | "
                f"{p50:.0f} | {p95:.0f} | {verdict} |"
            )
        lines.append("")
    baseline_rows = all_results[0][1]
    baseline_passes = all(
        key in baseline_rows
        and int(baseline_rows[key]["Failure Count"]) == 0
        and float(baseline_rows[key].get("95%") or 0) <= 1000
        for key in SCREENS
    )
    lines.extend(
        [
            "## Выводы",
            "",
            (
                "- На исходной настройке PostgreSQL все четыре экрана уложились в бюджет "
                "p95 ≤ 1 с."
                if baseline_passes
                else (
                    "- На исходной настройке есть превышения или ошибки; "
                    "им нужен отдельный разбор."
                )
            ),
            "- Глобальное `random_page_cost=1.1` не применяется автоматически: отчёт только "
            "сравнивает варианты, а runner всегда восстанавливает исходное значение.",
            "- Фильтр календаря использует полуоткрытый диапазон timestamp, поэтому PostgreSQL "
            "может применить индекс `(organization, starts_at)`.",
            f"- В БД находилось {scale['organizations']} организаций и "
            f"{scale['total_children']} детей суммарно; HTTP-профиль всегда обращался только к "
            "целевому tenant.",
            "",
            (
                "Отдельных тикетов производительности по основному прогону не требуется."
                if baseline_passes
                else "Для каждой строки с ❌ нужен отдельный тикет с CSV и `EXPLAIN ANALYZE`."
            ),
        ]
    )
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output
