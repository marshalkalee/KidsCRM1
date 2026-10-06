"""
Прогноз выручки от активных абонементов (TRU-125, ТЗ раздел 7).

Три разные величины — их нельзя складывать и путать:

1. «Оплачено, но не отработано» — деньги уже в кассе, занятия впереди.
   Это обязательство центра перед родителями, а не будущая выручка.
   По каждому активному или замороженному абонементу: оплачено минус
   стоимость уже отработанной части (по занятиям, у безлимитных — по
   дням), не меньше нуля.
2. «Продано, но не оплачено» — задолженность, та же цифра, что итог
   экрана «Задолженности» (subscriptions.debt).
3. «Ожидаемые продления» в следующем месяце: сколько продлений придётся
   на него × средняя цена продления. Продление — в день окончания
   абонемента с вероятностью = конверсии продлений за прошлые месяцы.
   Считаем цепочкой: месячный абонемент, который закончится в этом
   месяце, с вероятностью p продлят, продление той же длины закончится
   в следующем — и его продлят с вероятностью p (итого p²). Без цепочки
   месячные абонементы, которые ещё не проданы, из прогноза выпадали бы.
   Новые клиенты и оплаты долгов сюда не входят.

Честность прогноза: пока закончившихся абонементов в выборке мало,
прогноз не показываем; при средней выборке — только диапазон (90%
доверительный интервал Уилсона для конверсии); при достаточной — число и
диапазон. Ретроспектива: тот же расчёт «на 1-е число» прошлых месяцев
против того, что продлили на самом деле.
"""

import math
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from domains.money.subscriptions.debt import debt_total, debtor_subscriptions, paid_sum
from domains.money.subscriptions.models import Subscription
from domains.money.subscriptions.renewal_conversion import (
    RenewalIndex,
    add_months,
    grace_days,
    in_branches,
    load_rows,
    renewal_conversion,
)
from domains.platform.core.utils import today_for_org

# Конверсию считаем по абонементам, закончившимся за полгода: короче —
# мало данных, длиннее — устаревает (цены, состав групп).
LOOKBACK_MONTHS = 6
# Пороги достаточности данных (закончившихся абонементов в выборке) —
# решение по умолчанию, см. docs/project-status.md.
MIN_SAMPLE_RANGE = 20  # меньше — прогноз не показываем
MIN_SAMPLE_POINT = 60  # меньше — только диапазон
CONFIDENCE = 90
Z_SCORE = 1.645  # 90%
RETRO_MONTHS = 6
# Диапазон по одной выборке на большой базе получается слишком узким: он не
# знает о сезонности и о разбросе цен. Когда прошлых месяцев с прогнозом
# хватает, расширяем диапазон до худшей ошибки прогноза на них.
MIN_RETRO_FOR_CALIBRATION = 3

ACTIVE = (Subscription.Status.ACTIVE, Subscription.Status.FROZEN)


def _money(value) -> Decimal:
    return Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP)


def _month_end(first: date) -> date:
    return add_months(first, 1) - timedelta(days=1)


def wilson(successes: int, total: int) -> tuple[float, float]:
    """90% интервал Уилсона для доли: честнее «±», когда выборка мала
    или доля близка к 0 и 100%."""
    if not total:
        return 0.0, 1.0
    p = successes / total
    z2 = Z_SCORE**2
    centre = (p + z2 / (2 * total)) / (1 + z2 / total)
    spread = Z_SCORE * math.sqrt(p * (1 - p) / total + z2 / (4 * total**2)) / (1 + z2 / total)
    return max(0.0, centre - spread), min(1.0, centre + spread)


# ── 1. оплачено, но не отработано ───────────────────────────────────────────


def remaining_share(row, today) -> Decimal:
    """Доля абонемента, которая ещё впереди: 1 — не начат, 0 — отработан."""
    if row["starts_on"] > today:
        return Decimal(1)
    if not row["subscription_type_version__is_unlimited"]:
        quota = row["subscription_type_version__quota_sessions"] or 0
        if not quota:
            return Decimal(0)
        remaining = row["sessions_remaining_cache"]
        if remaining is None:
            remaining = quota
        return Decimal(min(max(remaining, 0), quota)) / Decimal(quota)
    total_days = (row["ends_on"] - row["starts_on"]).days
    if total_days <= 0 or today >= row["ends_on"]:
        return Decimal(0)
    return Decimal((row["ends_on"] - today).days) / Decimal(total_days)


def prepaid_unearned(scope, today) -> dict:
    qs = scope.filter(
        Subscription.objects.for_tenant(scope.organization).filter(status__in=ACTIVE),
        "branch_id",
    ).annotate(paid=paid_sum())
    rows = qs.values(
        "price",
        "paid",
        "starts_on",
        "ends_on",
        "sessions_remaining_cache",
        "subscription_type_version__is_unlimited",
        "subscription_type_version__quota_sessions",
    )
    value = Decimal(0)
    count = 0
    for row in rows:
        worked = row["price"] * (1 - remaining_share(row, today))
        unearned = row["paid"] - worked
        if unearned > 0:
            value += unearned
            count += 1
    return {"value": _money(value), "subscriptions": count}


# ── 2. продано, но не оплачено ──────────────────────────────────────────────


def unpaid(scope) -> dict:
    debtors = scope.filter(debtor_subscriptions(scope.organization), "branch_id")
    return {
        "value": _money(debt_total(scope.organization, branch_ids=scope.branch_ids)),
        "subscriptions": debtors.count(),
    }


# ── 3. прогноз продлений ────────────────────────────────────────────────────


# Абонемент короче недели — не повод считать по шесть продлений в месяц.
MIN_TERM_DAYS = 7


def _base(index, as_of, known_before, branch_ids, *, active_only):
    """Абонементы, от которых считается прогноз: известны на `known_before`,
    ещё не закончились на `as_of` и ещё не продлены. Статус в прошлом не
    хранится — для ретроспективы берём все, для «сейчас» — только активные
    и замороженные."""
    result = []
    for row in index.rows:
        if row.ends_on < as_of or row.created_on >= known_before:
            continue
        if not in_branches(row, branch_ids):
            continue
        if active_only and row.status not in ACTIVE:
            continue
        if index.renewal_of(row, known_before) is not None:
            continue
        result.append(row)
    return result


def _renewal_steps(row, month, month_end):
    """Номера продлений в цепочке (1 — продление этого абонемента, 2 —
    продление продления…), которые придутся на месяц: продление той же
    длины, что и абонемент."""
    term = timedelta(days=max((row.ends_on - row.starts_on).days, MIN_TERM_DAYS))
    step, day = 1, row.ends_on
    steps = []
    while day <= month_end:
        if day >= month:
            steps.append(step)
        step, day = step + 1, day + term
    return steps


def renewal_forecast(index, month, as_of, known_before, branch_ids, *, active_only=True) -> dict:
    """Продления, которые придутся на `month`, каким прогноз был бы на
    дату `as_of` (видно только проданное до `known_before`)."""
    month_end = _month_end(month)
    base = _base(index, as_of, known_before, branch_ids, active_only=active_only)
    chains = [(row, _renewal_steps(row, month, month_end)) for row in base]
    chains = [(row, steps) for row, steps in chains if steps]
    conversion = renewal_conversion(
        index, as_of=known_before, months=LOOKBACK_MONTHS, branch_ids=branch_ids
    )
    sample = conversion["ended"]
    if sample < MIN_SAMPLE_RANGE:
        status = "hidden"
    elif sample < MIN_SAMPLE_POINT:
        status = "range"
    else:
        status = "point"
    low_rate, high_rate = wilson(conversion["renewed"], sample)

    avg_check, avg_source = conversion["avg_renewal_price"], "renewals"
    if avg_check is None and base:
        avg_check = _money(sum((row.price for row in base), Decimal(0)) / len(base))
        avg_source = "base"
    if avg_check is None:
        avg_source = None

    def expected(rate):
        return sum(rate**step for _, steps in chains for step in steps)

    def amount(rate):
        if not chains:
            return Decimal(0)
        return _money(Decimal(str(expected(rate))) * avg_check)

    value = low = high = renewals = None
    if status != "hidden":
        low, high = amount(low_rate), amount(high_rate)
        if status == "point":
            value = amount(conversion["rate"])
            renewals = round(expected(conversion["rate"]), 1)
    return {
        "month": month.isoformat(),
        "as_of": as_of.isoformat(),
        "status": status,
        "base": len(base),
        # Абонементы, которые сами заканчиваются в этом месяце.
        "expiring": sum(1 for _, steps in chains if steps[0] == 1),
        "expected_renewals": renewals,
        "conversion": {
            "ended": sample,
            "renewed": conversion["renewed"],
            "rate": None if conversion["rate"] is None else round(conversion["rate"] * 100, 1),
            "low": round(low_rate * 100, 1) if sample else None,
            "high": round(high_rate * 100, 1) if sample else None,
            "window_start": conversion["window_start"].isoformat(),
            "window_end": conversion["window_end"].isoformat(),
        },
        "avg_check": avg_check,
        "avg_check_source": avg_source,
        "need_more": max(MIN_SAMPLE_RANGE - sample, 0),
        "value": value,
        "low": low,
        "high": high,
        "_base": base,
    }


def _fact(index, base, month, known_before):
    """Сколько на самом деле продлили в месяце по цепочкам от тех же
    абонементов: продление, продление продления… Новые клиенты не входят —
    их нет и в прогнозе."""
    month_end = _month_end(month)
    renewals = {}
    for row in base:
        current, seen = row, set()
        while current is not None and current.ends_on <= month_end and current.id not in seen:
            seen.add(current.id)
            renewal = index.renewal_of(current, known_before)
            if renewal is not None and current.ends_on >= month:
                renewals[renewal.id] = renewal.price
            current = renewal
    return len(renewals), _money(sum(renewals.values(), Decimal(0)))


def _retro_row(index, month, today, branch_ids) -> dict:
    """Прогноз на 1-е число месяца перед `month` против факта."""
    made_on = add_months(month, -1)
    forecast = renewal_forecast(index, month, made_on, made_on, branch_ids, active_only=False)
    base = forecast.pop("_base")
    fact_renewed, fact = _fact(index, base, month, today + timedelta(days=1))
    deviation = None
    if forecast["value"]:
        deviation = round(float((fact - forecast["value"]) * 100 / forecast["value"]), 1)
    in_range = None
    if forecast["low"] is not None:
        in_range = forecast["low"] <= fact <= forecast["high"]
    # Окно продления для конца месяца ещё идёт — факт дособирается.
    settles_on = _month_end(month) + timedelta(days=index.grace_days)
    return {
        **forecast,
        "fact_renewed": fact_renewed,
        "fact": fact,
        "deviation_percent": deviation,
        "in_range": in_range,
        "complete": settles_on < today,
        "settles_on": settles_on.isoformat(),
    }


def calibrate(forecast, retrospective) -> None:
    """Расширить диапазон прогноза до худшей ошибки на законченных прошлых
    месяцах (в процентах), если таких месяцев не меньше трёх."""
    errors = [
        abs(row["deviation_percent"])
        for row in retrospective
        if row["complete"] and row["deviation_percent"] is not None
    ]
    forecast["calibration_percent"] = None
    if len(errors) < MIN_RETRO_FOR_CALIBRATION or forecast["low"] is None:
        return
    worst = Decimal(str(max(errors))) / 100
    centre = forecast["value"]
    if centre is None:
        centre = (forecast["low"] + forecast["high"]) / 2
    forecast["low"] = min(forecast["low"], _money(centre * (1 - worst)))
    forecast["high"] = max(forecast["high"], _money(centre * (1 + worst)))
    forecast["calibration_percent"] = max(errors)


def revenue_forecast(scope) -> dict:
    organization = scope.organization
    today = today_for_org(organization)
    next_month = add_months(today.replace(day=1), 1)
    first_retro = add_months(today.replace(day=1), -RETRO_MONTHS)
    # Самая ранняя выборка конверсии — для первой ретроспективы.
    since = add_months(add_months(first_retro, -1), -LOOKBACK_MONTHS)
    index = RenewalIndex(load_rows(organization, ends_since=since), grace_days(organization))
    branch_ids = scope.branch_ids

    forecast = renewal_forecast(index, next_month, today, today + timedelta(days=1), branch_ids)
    forecast.pop("_base")
    retrospective = [
        _retro_row(index, add_months(first_retro, offset), today, branch_ids)
        for offset in range(RETRO_MONTHS)
    ]
    calibrate(forecast, retrospective)
    return {
        "today": today.isoformat(),
        "prepaid": prepaid_unearned(scope, today),
        "unpaid": unpaid(scope),
        "forecast": forecast,
        "retrospective": retrospective,
        "rules": {
            "grace_days": index.grace_days,
            "lookback_months": LOOKBACK_MONTHS,
            "min_sample_range": MIN_SAMPLE_RANGE,
            "min_sample_point": MIN_SAMPLE_POINT,
            "confidence": CONFIDENCE,
        },
    }
