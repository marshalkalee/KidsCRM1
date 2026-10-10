"""
Средний чек и динамика задолженности (TRU-124, ТЗ раздел 7: «задолженности,
средний чек» в дашборде владельца).

Средний чек — средняя цена проданного абонемента (со скидкой) по дате
продажи; та же цифра, что метрика `average_check`. Среднее чувствительно к
выбросам: один годовой абонемент перекашивает месяц восьмизанятийных. Поэтому
рядом всегда медиана, квартили и распределение по ценам, а влияние скидок —
отдельно: средний чек без скидок против фактического, причины скидок.

Долг — только из `subscriptions.debt` (TRU-73): за период, который идёт по
сегодня, — живая цифра, та же, что итог экрана «Задолженности»; за прошлые
даты — почасовые снимки (`MetricSnapshot`, ADR-0006), задним числом долг не
пересчитывается. Погашение долгов на начало периода — `repaid_debt`.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

import pytz
from django.db.models import Aggregate, Count, F, FloatField, Max, Min, Q, Sum
from django.db.models.functions import Coalesce, TruncMonth

from domains.money.subscriptions.debt import DEBT_AGE_BUCKETS, debt_structure, repaid_debt
from domains.platform.core.utils import today_for_org

from .breakdowns import DIMENSIONS
from .metrics import CLIENT_SOURCE, SALE_CLIENT_KIND, children_in_scope, sold_subscriptions
from .models import MetricSnapshot
from .period import Period, _add_months
from .registry import cached

# Разрезы среднего чека: ключ → поле строки продажи.
CHECK_DIMENSIONS = ("branch", "direction", "subscription_type", "source", "client")
MONTHS = 12
# Не больше стольких столбцов в распределении цен.
MAX_BINS = 8
NICE_STEPS = (1000, 2000, 2500, 5000, 10000, 20000, 25000, 50000, 100000, 200000, 500000)
# Снимок старше недели к нужной дате не подставляем: лучше «нет данных».
SNAPSHOT_WINDOW_DAYS = 6
AGE_KEYS = [key for key, _ in DEBT_AGE_BUCKETS]
DEBT_METRICS = ["debt_total", *[f"debt_age_{key}" for key in AGE_KEYS], "debtors_share"]


def _str(value):
    """Деньги строкой, как в остальном API: «22500», «22333.3»."""
    if value is None:
        return None
    value = Decimal(value)
    return str(int(value)) if value == value.to_integral() else f"{value:f}"


def _round(value, places=1):
    if value is None:
        return None
    return Decimal(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _pct(part, whole):
    if not whole:
        return None
    return _round(Decimal(part) * 100 / Decimal(whole))


class Percentile(Aggregate):
    """Перцентиль Postgres с интерполяцией (медиана — 0.5): та же формула,
    что statistics.quantiles(method="inclusive"). Считается в базе — год
    продаж центра не тянем строками в Python."""

    function = "PERCENTILE_CONT"
    template = "%(function)s(%(fraction)s) WITHIN GROUP (ORDER BY %(expressions)s)"
    output_field = FloatField()

    def __init__(self, expression, fraction, **extra):
        super().__init__(expression, fraction=fraction, **extra)


STATS = {
    "count": Count("id"),
    "amount": Sum("price"),
    "p25": Percentile("price", 0.25),
    "median": Percentile("price", 0.5),
    "p75": Percentile("price", 0.75),
    "min": Min("price"),
    "max": Max("price"),
}


def _stats(row) -> dict:
    """Строка агрегата STATS → среднее, медиана, квартили, мин/макс."""
    count = row.get("count") or 0
    if not count:
        return {
            "count": 0,
            "amount": "0",
            "average": None,
            "median": None,
            "p25": None,
            "p75": None,
            "min": None,
            "max": None,
        }
    amount = Decimal(row["amount"])
    return {
        "count": count,
        "amount": _str(amount),
        "average": _str(_round(amount / count)),
        **{key: _str(_round(Decimal(str(row[key])))) for key in ("median", "p25", "p75")},
        "min": _str(row["min"]),
        "max": _str(row["max"]),
    }


def _nice_step(low, high):
    span = high - low
    for step in NICE_STEPS:
        if span / step < MAX_BINS:
            return step
    return NICE_STEPS[-1] * (int(span // (NICE_STEPS[-1] * MAX_BINS)) + 1)


def distribution(counts) -> list:
    """Сколько абонементов продано в каждом ценовом интервале [from, to).
    counts — {цена: сколько продано по этой цене}."""
    if not counts:
        return []
    low, high = min(counts), max(counts)
    step = _nice_step(low, high)
    start = int(low // step) * step
    bins = defaultdict(int)
    for price, number in counts.items():
        bins[int((price - start) // step)] += number
    total = sum(counts.values())
    return [
        {
            "from": str(start + index * step),
            "to": str(start + (index + 1) * step),
            "count": bins.get(index, 0),
            "share": _str(_pct(bins.get(index, 0), total)),
        }
        for index in range(max(bins) + 1)
    ]


def _sold_between(scope, start, end):
    return sold_subscriptions(scope).filter(created_at__gte=start, created_at__lt=end).order_by()


# Разрез → поле или выражение для GROUP BY (источник — подзапрос, как в реестре).
CHECK_FIELDS = {
    "branch": F("branch_id"),
    "direction": F("direction_id"),
    "subscription_type": F("subscription_type_version__subscription_type_id"),
    "source": CLIENT_SOURCE,
    "client": SALE_CLIENT_KIND,
}


def _by(scope, qs, dimension):
    rows = qs.annotate(_key=CHECK_FIELDS[dimension]).values("_key").annotate(**STATS)
    rows = list(rows)
    labels = DIMENSIONS[dimension](scope.organization, [row["_key"] for row in rows if row["_key"]])
    items = [
        {
            "key": str(row["_key"]) if row["_key"] not in (None, "") else None,
            "label": labels.get(row["_key"]) if row["_key"] not in (None, "") else None,
            **_stats(row),
        }
        for row in rows
    ]
    return sorted(items, key=lambda item: item["count"], reverse=True)


def _discounts(scope, qs) -> dict:
    totals = qs.aggregate(
        count=Count("id"),
        amount=Coalesce(Sum("price"), Decimal(0)),
        list_total=Coalesce(Sum("list_price"), Decimal(0)),
        total=Coalesce(Sum("discount_amount"), Decimal(0)),
        discounted=Count("id", filter=Q(discount_amount__gt=0)),
    )
    count = totals["count"]
    list_average = _round(totals["list_total"] / count) if count else None
    average = _round(totals["amount"] / count) if count else None
    reasons = list(
        qs.filter(discount_amount__gt=0)
        .values("discount_reason")
        .annotate(count=Count("id"), amount=Sum("discount_amount"))
        .order_by("-amount")
    )
    labels = DIMENSIONS["discount_reason"](
        scope.organization, [row["discount_reason"] for row in reasons]
    )
    return {
        "total": _str(totals["total"]),
        "count": totals["discounted"],
        "share_of_sales": _str(_pct(totals["discounted"], count)),
        # Без скидок средний чек был бы таким — разница и есть влияние скидок.
        "list_average": _str(list_average),
        "average": _str(average),
        "effect": _str(list_average - average) if count else None,
        "effect_percent": _str(_pct(list_average - average, list_average)) if count else None,
        "share_of_list": _str(_pct(totals["total"], totals["list_total"])),
        "reasons": [
            {
                "key": row["discount_reason"] or None,
                "label": labels.get(row["discount_reason"]) if row["discount_reason"] else None,
                "count": row["count"],
                "amount": _str(row["amount"]),
            }
            for row in reasons
        ],
    }


def _months(period, months=MONTHS) -> list[date]:
    last = period.end.replace(day=1)
    return [_add_months(last, -shift) for shift in range(months - 1, -1, -1)]


def _monthly_check(scope, period):
    months = _months(period)
    start = Period(months[0], period.end).bounds(scope.organization)[0]
    end = period.bounds(scope.organization)[1]
    tz = pytz.timezone(scope.organization.timezone)
    rows = (
        _sold_between(scope, start, end)
        .annotate(month=TruncMonth("created_at", tzinfo=tz))
        .values("month")
        .annotate(**STATS, discount=Sum("discount_amount"))
    )
    by_month = {}
    for row in rows:
        month = row["month"].date() if hasattr(row["month"], "date") else row["month"]
        by_month[month.replace(day=1)] = row
    result = []
    for month in months:
        row = by_month.get(month, {})
        stats = _stats(row)
        result.append(
            {
                "month": month.isoformat(),
                "count": stats["count"],
                "average": stats["average"],
                "median": stats["median"],
                "discount_total": _str(row.get("discount") or Decimal(0)),
            }
        )
    return result


def average_check(scope, period) -> dict:
    """Средний чек за период: сводка с медианой, прошлый период, распределение
    по ценам, разрезы, скидки, помесячная динамика за 12 месяцев до конца
    периода."""

    def run():
        qs = _sold_between(scope, *period.bounds(scope.organization))
        previous = _sold_between(scope, *period.previous().bounds(scope.organization))
        counts = dict(qs.values("price").annotate(n=Count("id")).values_list("price", "n"))
        return {
            "summary": _stats(qs.aggregate(**STATS)),
            "previous": _stats(previous.aggregate(**STATS)),
            "distribution": distribution(counts),
            "by": {dimension: _by(scope, qs, dimension) for dimension in CHECK_DIMENSIONS},
            "discounts": _discounts(scope, qs),
            "monthly": _monthly_check(scope, period),
        }

    key = f"ac:{scope.cache_key}:{period.start}:{period.end}:{period.preset}"
    return cached(key, period, scope, run)


# ── задолженность ───────────────────────────────────────────────────────────


def _live_point(scope, day):
    data = debt_structure(scope.organization, branch_ids=scope.branch_ids)
    active = set(children_in_scope(scope).values_list("id", flat=True))
    debtors_active = len(data["child_ids"] & active)
    return {
        "date": day.isoformat(),
        "source": "live",
        "total": _str(data["total"]),
        "by_age": {key: _str(value) for key, value in data["by_age"].items()},
        "debtors": len(data["child_ids"]),
        "debtors_active": debtors_active,
        "active_children": len(active),
        "debtors_share": _str(_pct(debtors_active, len(active))),
    }


class _Snapshots:
    """Снимки долга в выборке филиалов: вся организация — строка без
    филиала; филиалы — сумма их строк (доля должников — только для одного)."""

    def __init__(self, scope, first_day, last_day):
        self.scope = scope
        rows = MetricSnapshot.objects.for_tenant(scope.organization).filter(
            metric__in=DEBT_METRICS,
            date__gte=first_day - timedelta(days=SNAPSHOT_WINDOW_DAYS),
            date__lte=last_day,
        )
        if scope.branch_ids is None:
            rows = rows.filter(branch__isnull=True)
        else:
            rows = rows.filter(branch_id__in=scope.branch_ids)
        # {(метрика, филиал): [(дата, значение)] по возрастанию даты}
        self.rows = defaultdict(list)
        for metric, branch_id, day, value in rows.order_by("date").values_list(
            "metric", "branch_id", "date", "value"
        ):
            self.rows[(metric, branch_id)].append((day, value))

    def _value(self, metric, day):
        found, total = False, Decimal(0)
        for (name, _), points in self.rows.items():
            if name != metric:
                continue
            latest = [v for d, v in points if day - timedelta(SNAPSHOT_WINDOW_DAYS) <= d <= day]
            if latest and latest[-1] is not None:
                found, total = True, total + latest[-1]
        return total if found else None

    def point(self, day):
        total = self._value("debt_total", day)
        if total is None:
            return {"date": day.isoformat(), "source": None, "total": None, "by_age": None}
        single = self.scope.branch_ids is None or len(self.scope.branch_ids) == 1
        return {
            "date": day.isoformat(),
            "source": "snapshot",
            "total": _str(total),
            "by_age": {key: _str(self._value(f"debt_age_{key}", day)) for key in AGE_KEYS},
            "debtors_share": _str(self._value("debtors_share", day)) if single else None,
        }


def debt_dynamics(scope, period) -> dict:
    """Долг на конец периода (живой, если период идёт по сегодня), на конец
    прошлого периода, по месяцам за 12 месяцев, структура по давности, доля
    должников и сколько из долга на начало периода погашено."""

    def run():
        today = today_for_org(scope.organization)
        months = _months(period)
        previous_end = period.previous().end
        snapshots = _Snapshots(scope, min(months[0], previous_end), period.end)

        live = {}

        def point(day):
            if day < today:
                return snapshots.point(day)
            # Живая цифра одна на весь ответ: конец периода и текущий месяц — это она.
            if "point" not in live:
                live["point"] = _live_point(scope, today)
            return live["point"]

        end = point(period.end)
        before = point(previous_end)
        change = None
        if end["total"] is not None and before["total"] is not None:
            change = Decimal(end["total"]) - Decimal(before["total"])
        monthly = []
        for month in months:
            month_end = min(_add_months(month, 1) - timedelta(days=1), period.end)
            monthly.append({"month": month.isoformat(), **point(month_end)})

        start, finish = period.bounds(scope.organization)
        owed, repaid = repaid_debt(scope.organization, start, finish, branch_ids=scope.branch_ids)
        history = MetricSnapshot.objects.for_tenant(scope.organization).filter(metric="debt_total")
        history = (
            history.filter(branch__isnull=True)
            if scope.branch_ids is None
            else history.filter(branch_id__in=scope.branch_ids)
        )
        first = history.order_by("date").values_list("date", flat=True).first()
        return {
            "end": end,
            "previous": before,
            "change": _str(change),
            "change_percent": _str(
                _pct(change, Decimal(before["total"])) if change is not None else None
            ),
            "monthly": monthly,
            "repaid": {
                "owed_at_start": _str(owed),
                "repaid": _str(repaid),
                "remaining": _str(owed - repaid),
                "percent": _str(_pct(repaid, owed)),
            },
            "history_since": first.isoformat() if first else None,
        }

    key = f"dd:{scope.cache_key}:{period.start}:{period.end}:{period.preset}"
    return cached(key, period, scope, run)
