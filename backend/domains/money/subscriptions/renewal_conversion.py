"""
Конверсия продлений (ТЗ п. 5.3): сколько абонементов продлено из числа
закончившихся. Нужна прогнозу выручки (TRU-125, ТЗ раздел 7); отчёт по
конверсии и колонка в сравнении филиалов (TRU-126) берут её отсюда же.

Что считаем продлением — пока решение по умолчанию, вопрос №5 в
docs/project-status.md (окно N дней, летний перерыв). Абонемент продлён,
если у того же ребёнка есть другой абонемент:
- проданный кнопкой «Продлить» (renewed_from указывает на этот), или
- того же направления, начавшийся позже этого и не позже чем через
  RENEWAL_GRACE_DAYS дней после его окончания.
Ответ владельца меняет только RENEWAL_GRACE_DAYS и `_is_renewal`.

Расчёт «на дату» (as_of): видно только то, что было создано до неё.
Так ретроспектива честно восстанавливает прогноз прошлого месяца, не
подглядывая в продажи, которых тогда ещё не было.
"""

import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import pytz

from .models import Subscription

# Купил новый абонемент в течение двух недель после окончания — продлил.
RENEWAL_GRACE_DAYS = 14


@dataclass(frozen=True)
class SubscriptionRow:
    id: object
    child_id: object
    direction_id: object
    branch_id: object
    starts_on: date
    ends_on: date
    created_on: date  # дата продажи по времени центра
    price: Decimal
    renewed_from_id: object
    status: str


def add_months(day: date, months: int) -> date:
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def load_rows(organization, *, ends_since: date) -> list[SubscriptionRow]:
    """Все абонементы центра, закончившиеся не раньше `ends_since`, одним
    запросом — без филиала: ребёнок мог продлиться в другом филиале."""
    tz = pytz.timezone(organization.timezone)
    rows = (
        Subscription.objects.for_tenant(organization)
        .filter(ends_on__gte=ends_since)
        .values_list(
            "id",
            "child_id",
            "direction_id",
            "branch_id",
            "starts_on",
            "ends_on",
            "created_at",
            "price",
            "renewed_from_id",
            "status",
        )
    )
    return [
        SubscriptionRow(
            pk,
            child_id,
            direction_id,
            branch_id,
            starts_on,
            ends_on,
            created_at.astimezone(tz).date(),
            price,
            renewed_from_id,
            status,
        )
        for (
            pk,
            child_id,
            direction_id,
            branch_id,
            starts_on,
            ends_on,
            created_at,
            price,
            renewed_from_id,
            status,
        ) in rows
    ]


def _is_renewal(candidate: SubscriptionRow, row: SubscriptionRow) -> bool:
    if candidate.id == row.id:
        return False
    if candidate.renewed_from_id == row.id:
        return True
    return (
        candidate.direction_id == row.direction_id
        and row.starts_on < candidate.starts_on <= row.ends_on + timedelta(days=RENEWAL_GRACE_DAYS)
    )


class RenewalIndex:
    """Поиск продления абонемента среди загруженных строк (по ребёнку)."""

    def __init__(self, rows):
        self.rows = rows
        self._by_child = defaultdict(list)
        for row in sorted(rows, key=lambda r: (r.starts_on, r.created_on)):
            self._by_child[row.child_id].append(row)

    def renewal_of(self, row: SubscriptionRow, known_before: date):
        """Первый абонемент-продление, проданный до `known_before`, или None."""
        for candidate in self._by_child[row.child_id]:
            if candidate.created_on < known_before and _is_renewal(candidate, row):
                return candidate
        return None


def in_branches(row, branch_ids) -> bool:
    return branch_ids is None or row.branch_id in branch_ids


def renewal_conversion(index: RenewalIndex, *, as_of: date, months: int, branch_ids=None) -> dict:
    """Конверсия по абонементам, закончившимся за `months` месяцев до
    `as_of`, у которых окно продления уже прошло (иначе «не продлил» ещё
    рано записывать). Видно только проданное до `as_of`.

    {ended, renewed, rate (0..1 | None), avg_renewal_price, window_start, window_end}
    """
    window_start = add_months(as_of, -months)
    window_end = as_of - timedelta(days=RENEWAL_GRACE_DAYS + 1)
    ended = renewed = 0
    renewal_prices = {}
    for row in index.rows:
        if not (window_start <= row.ends_on <= window_end):
            continue
        if row.created_on >= as_of or not in_branches(row, branch_ids):
            continue
        ended += 1
        renewal = index.renewal_of(row, as_of)
        if renewal is not None:
            renewed += 1
            renewal_prices[renewal.id] = renewal.price
    avg_price = None
    if renewal_prices:
        avg_price = (sum(renewal_prices.values(), Decimal(0)) / len(renewal_prices)).quantize(
            Decimal(1)
        )
    return {
        "ended": ended,
        "renewed": renewed,
        "rate": renewed / ended if ended else None,
        "avg_renewal_price": avg_price,
        "window_start": window_start,
        "window_end": window_end,
    }
