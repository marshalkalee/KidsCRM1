"""
Реестр метрик (TRU-118, ADR-0006). Отчёт не пишет свой SQL по живым
таблицам и свой выбор периода — он регистрирует метрику и получает
значение, сравнение с прошлым периодом, график и признак «данных пока
мало» одинаково для всех отчётов.

Два вида метрик:
- событийная (`EventMetric`) — сумма или количество событий с датой:
  оплаты, посещения, новые заявки. Значение, прошлый период и график
  считаются по одному queryset, группировкой в базе (TruncDay/Week/Month
  в поясе центра);
- снимок (`SnapshotMetric`) — состояние «на сейчас»: долг, дети в группах.
  Прошлого периода и графика нет — у снимка нет истории, пока её не
  начнут сохранять (см. ADR-0006, «Последствия»).

Метрика, которая уже считается в операционке (долг, заполняемость),
берётся из того же сервиса, а не пересчитывается здесь.
"""

import logging
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytz
from django.core.cache import caches
from django.db import connection, transaction
from django.db.models import Count, Min, Sum
from django.db.models.functions import TruncDay, TruncMonth, TruncWeek

from domains.platform.core.utils import today_for_org

from .period import Period, bucket_start

CACHE_ALIAS = "analytics"
# Прошлое почти не меняется (оплату задним числом отменяют редко) —
# держим час; период, куда входит сегодня, — минуту, чтобы только что
# принятая оплата появилась на дашборде почти сразу.
CLOSED_PERIOD_TTL = 60 * 60
OPEN_PERIOD_TTL = 60

TRUNC = {"day": TruncDay, "week": TruncWeek, "month": TruncMonth}

# Аналитический запрос, который считается дольше, прерывается, а не держит
# соединение и строки базы, нужные администратору у стойки.
STATEMENT_TIMEOUT_MS = 15_000
# Postgres по умолчанию считает базу на HDD (random_page_cost=4) и на
# отчётах за месяц читает всю посещаемость подряд вместо индекса. Для SSD
# правильно 1.1 — ставим только аналитическим запросам, замер в ADR-0006.
RANDOM_PAGE_COST = 1.1
# «Сколько разных детей ходило за год» сортирует сотни тысяч строк: при
# 4 МБ по умолчанию сортировка уходит на диск. Только для аналитики.
WORK_MEM = "32MB"
# Дата первых данных меняется раз в жизни центра — не считаем её каждую минуту.
DATA_SINCE_TTL = 6 * 60 * 60

# Значения, уже посчитанные в этом вызове compute(): «доля посещений»
# берёт «посещения» и «отметки», а не считает их второй раз.
_memo: ContextVar[dict | None] = ContextVar("analytics_memo", default=None)


def _memoized(what, metric, scope, period, func):
    memo = _memo.get()
    if memo is None:
        return func()
    key = (what, metric.name, scope.cache_key, period)
    if key not in memo:
        memo[key] = func()
    return memo[key]


def value_of(name, scope, period):
    metric = REGISTRY[name]
    return _memoized("value", metric, scope, period, lambda: metric.value(scope, period))


def series_of(name, scope, period):
    metric = REGISTRY[name]
    return _memoized("series", metric, scope, period, lambda: metric.series(scope, period))


REGISTRY: dict[str, "Metric"] = {}

logger = logging.getLogger(__name__)


def _cache_get(key):
    # Redis недоступен — отчёт просто считается заново, а не падает.
    try:
        return caches[CACHE_ALIAS].get(key)
    except Exception:
        logger.warning("analytics cache unavailable", exc_info=True)
        return None


def _cache_set(key, value, ttl):
    try:
        caches[CACHE_ALIAS].set(key, value, ttl)
    except Exception:
        logger.warning("analytics cache unavailable", exc_info=True)


@dataclass(frozen=True)
class Metric:
    name: str
    label: str
    # money — тенге, count — штуки, percent — 0–100.
    unit: str
    # Откуда цифра — для ADR и подсказки в интерфейсе.
    source: str
    # Сколько дней истории нужно, чтобы метрике можно было верить. Меньше —
    # отчёт показывает «данных пока мало», а не график из двух точек.
    min_history_days: int = 0

    kind = "abstract"

    def value(self, scope, period: Period):
        raise NotImplementedError

    def series(self, scope, period: Period) -> list | None:
        return None

    def data_since(self, scope) -> date | None:
        return None


@dataclass(frozen=True)
class EventMetric(Metric):
    # (scope) -> queryset событий в выборке филиалов, ещё без периода.
    queryset: Callable = None
    # Поле даты события (DateTimeField) — по нему период и график.
    date_field: str = ""
    # Что считаем: Sum("amount"), Count("id"), Count("child_id", distinct=True).
    aggregate: Callable = None
    # Разбивки: {"измерение": "путь до поля"} — {"method": "method",
    # "branch": "subscription__branch_id"}. Подписи — breakdowns.DIMENSIONS.
    breakdowns: dict = None

    kind = "event"

    def _in_period(self, scope, period):
        start, end = period.bounds(scope.organization)
        # order_by() — без сортировки модели по умолчанию: для суммы она не
        # нужна, а на сотнях тысяч строк Postgres сортировал бы их на диске.
        return (
            self.queryset(scope)
            .filter(**{f"{self.date_field}__gte": start, f"{self.date_field}__lt": end})
            .order_by()
        )

    def value(self, scope, period):
        return self._in_period(scope, period).aggregate(v=self.aggregate())["v"] or 0

    def series(self, scope, period):
        step = period.granularity
        tz = pytz.timezone(scope.organization.timezone)
        rows = (
            self._in_period(scope, period)
            .annotate(bucket=TRUNC[step](self.date_field, tzinfo=tz))
            .values("bucket")
            .annotate(v=self.aggregate())
            .values_list("bucket", "v")
        )
        by_bucket = {}
        for bucket, value in rows:
            day = bucket.date() if hasattr(bucket, "date") else bucket
            by_bucket[bucket_start(day, step)] = value or 0
        return [(day, by_bucket.get(day, 0)) for day in period.bucket_starts()]

    def breakdown(self, scope, period, dimension):
        """[(ключ, значение)] за период по одному измерению, по убыванию."""
        field = (self.breakdowns or {})[dimension]
        rows = (
            self._in_period(scope, period)
            .values(field)
            .annotate(v=self.aggregate())
            .values_list(field, "v")
        )
        return sorted(((key, v or 0) for key, v in rows), key=lambda row: row[1], reverse=True)

    def data_since(self, scope):
        first = self.queryset(scope).order_by().aggregate(first=Min(self.date_field))["first"]
        if first is None:
            return None
        return first.astimezone(pytz.timezone(scope.organization.timezone)).date()


@dataclass(frozen=True)
class SnapshotMetric(Metric):
    # (scope) -> число «на сейчас»
    compute: Callable = None

    kind = "snapshot"

    def value(self, scope, period):
        return self.compute(scope)

    def series(self, scope, period):
        # История — из ночных снимков (snapshots.py); сегодняшняя точка — живое значение.
        from .snapshots import history

        return history(self, scope, period)


@dataclass(frozen=True)
class RatioMetric(Metric):
    """Отношение двух событийных метрик: средний чек = выручка / оплаты,
    доля посещений = был / (был + не был). Проценты — 0–100."""

    numerator: str = ""
    denominator: str = ""
    scale: int = 1

    kind = "ratio"

    def _ratio(self, top, bottom):
        if not bottom:
            return None
        return round(Decimal(top) * self.scale / Decimal(bottom), 1)

    def value(self, scope, period):
        return self._ratio(
            value_of(self.numerator, scope, period),
            value_of(self.denominator, scope, period),
        )

    def series(self, scope, period):
        top = dict(series_of(self.numerator, scope, period))
        bottom = dict(series_of(self.denominator, scope, period))
        return [(day, self._ratio(top[day], bottom[day])) for day in period.bucket_starts()]

    def data_since(self, scope):
        return REGISTRY[self.denominator].data_since(scope)


def register(metric: Metric) -> Metric:
    if metric.name in REGISTRY:
        raise ValueError(f"Метрика {metric.name} уже зарегистрирована")
    REGISTRY[metric.name] = metric
    return metric


def _number(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        # Строкой, как деньги в остальном API; без экспоненты («2.6725E+6»).
        return str(int(value)) if value == value.to_integral() else f"{value:f}"
    return value


def _change_percent(current, previous):
    if current is None or previous in (None, 0):
        return None
    return round((Decimal(current) - Decimal(previous)) * 100 / Decimal(previous), 1)


def _compute(metric: Metric, scope, period: Period, *, compare: bool, series: bool) -> dict:
    today = today_for_org(scope.organization)
    value = value_of(metric.name, scope, period)
    result = {
        "label": metric.label,
        "unit": metric.unit,
        "kind": metric.kind,
        "source": metric.source,
        "value": _number(value),
    }
    if metric.kind == "snapshot":
        points = series_of(metric.name, scope, period) if (series or compare) else None
        if series:
            result["series"] = (
                None
                if points is None
                else [{"date": day.isoformat(), "value": _number(v)} for day, v in points]
            )
        if compare:
            # Прошлое значение — снимок на конец прошлого периода, если он был.
            previous_points = series_of(metric.name, scope, period.previous())
            previous = previous_points[-1][1] if previous_points else None
            result["previous"] = _number(previous)
            result["change_percent"] = _number(_change_percent(value, previous))
        # Сам снимок верен с первого дня; история копится с первого ночного снимка.
        result.update(data_since=None, enough_data=True, days_until_enough=0)
        return result
    if compare:
        previous = value_of(metric.name, scope, period.previous())
        if series:
            # Прошлый период той же длины — пунктиром под текущим, точка к точке.
            result["previous_series"] = [
                {"date": day.isoformat(), "value": _number(v)}
                for day, v in series_of(metric.name, scope, period.previous())
            ]
        result["previous"] = _number(previous)
        result["change_percent"] = _number(_change_percent(value, previous))
    if series:
        result["series"] = [
            {"date": day.isoformat(), "value": _number(v)}
            for day, v in series_of(metric.name, scope, period)
        ]
    since_key = f"since:{metric.name}:{scope.cache_key}"
    since = _cache_get(since_key)
    if since is None:
        since = metric.data_since(scope) or ""
        # «Данных ещё нет» не держим долго — первая оплата должна появиться сразу.
        _cache_set(since_key, since, DATA_SINCE_TTL if since else OPEN_PERIOD_TTL)
    since = since or None
    history_days = (today - since).days + 1 if since else 0
    result["data_since"] = since.isoformat() if since else None
    result["enough_data"] = since is not None and history_days >= metric.min_history_days
    result["days_until_enough"] = (
        metric.min_history_days if since is None else max(metric.min_history_days - history_days, 0)
    )
    return result


def cached(key, period, scope, func):
    """Кэш для разбивок и тепловой карты — те же сроки, что у метрик."""
    value = _cache_get(key)
    if value is None:
        with transaction.atomic():
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")
                    cursor.execute(f"SET LOCAL random_page_cost = {RANDOM_PAGE_COST}")
                    cursor.execute(f"SET LOCAL work_mem = '{WORK_MEM}'")
            value = func()
        open_period = period.end >= today_for_org(scope.organization)
        _cache_set(key, value, OPEN_PERIOD_TTL if open_period else CLOSED_PERIOD_TTL)
    return value


def compute(names, scope, period: Period, *, compare=True, series=True, use_cache=True) -> dict:
    """{имя: {value, previous, change_percent, series, enough_data, …}} —
    ответ API и то, что покажет плитка/график каркаса дашборда."""
    unknown = [name for name in names if name not in REGISTRY]
    if unknown:
        raise KeyError(", ".join(unknown))
    open_period = period.end >= today_for_org(scope.organization)
    results = {}
    token = _memo.set({})
    try:
        with transaction.atomic():
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")
                    cursor.execute(f"SET LOCAL random_page_cost = {RANDOM_PAGE_COST}")
                    cursor.execute(f"SET LOCAL work_mem = '{WORK_MEM}'")
            for name in names:
                metric = REGISTRY[name]
                key = (
                    f"m:{name}:{scope.cache_key}:{period.start}:{period.end}:{period.preset}"
                    f":{int(compare)}{int(series)}"
                )
                cached = _cache_get(key) if use_cache else None
                if cached is None:
                    cached = _compute(metric, scope, period, compare=compare, series=series)
                    ttl = (
                        OPEN_PERIOD_TTL
                        if open_period or metric.kind == "snapshot"
                        else CLOSED_PERIOD_TTL
                    )
                    _cache_set(key, cached, ttl)
                results[name] = cached
    finally:
        _memo.reset(token)
    return results


# Используются в metrics.py для aggregate=…
def total(field):
    return lambda: Sum(field)


def count(field="id", distinct=False):
    return lambda: Count(field, distinct=distinct)
