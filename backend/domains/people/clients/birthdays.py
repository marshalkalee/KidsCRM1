"""
Дни рождения на главной: кто из детей отмечает в ближайшие дни — повод
поздравить семью. Только те, кто ходит (активные и на пробном).
"""

import datetime

from domains.platform.core.utils import today_for_org

from .models import Child

MAX_DAYS = 31


def _next_birthday(birth_date, today):
    for year in (today.year, today.year + 1):
        try:
            day = birth_date.replace(year=year)
        except ValueError:  # 29 февраля в невисокосный год — отмечают 28-го
            day = datetime.date(year, 2, 28)
        if day >= today:
            return day
    return None


def upcoming_birthdays(organization, days=7):
    days = max(0, min(int(days), MAX_DAYS))
    today = today_for_org(organization)
    rows = []
    children = (
        Child.objects.for_tenant(organization)
        .filter(status__in=(Child.Status.ACTIVE, Child.Status.TRIAL), birth_date__isnull=False)
        .values("id", "full_name", "birth_date")
    )
    for child in children:
        day = _next_birthday(child["birth_date"], today)
        if day and (day - today).days <= days:
            rows.append(
                {
                    "id": str(child["id"]),
                    "full_name": child["full_name"],
                    "date": day.isoformat(),
                    "days_until": (day - today).days,
                    "turns": day.year - child["birth_date"].year,
                }
            )
    return sorted(rows, key=lambda r: (r["days_until"], r["full_name"]))
