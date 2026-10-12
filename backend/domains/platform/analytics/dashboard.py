"""
Главный экран дашборда владельца (TRU-129, ТЗ раздел 7): семь цифр
верхнего уровня за выбранный период и филиалы, каждая — вход в свой
подробный отчёт.

Модуль ничего не считает сам: каждая цифра берётся из той же функции,
что её подробный отчёт или операционный экран, поэтому расходиться им
нечему.
- Выручка — метрика revenue (сумма оплат в карточках детей).
- Задолженность — debt_total, итог экрана «Задолженности»; динамика —
  ночной снимок на конец прошлого периода (ADR-0006).
- Заполняемость — group_fill, дети в группах / места, как в списке групп;
  «с недобором» — тот же порог и та же формула, что пометка в списке групп.
- Конверсия заявок — воронка (TRU-115): купили / новые заявки периода.
- Конверсия продлений — итог отчёта «Продления» (TRU-126).
- Зона ухода — итог риск-листа (TRU-122).
- Прогноз выручки — ожидаемые продления следующего месяца (TRU-125).

Одна упавшая цифра (например, прервана по таймауту) не роняет экран:
плитка придёт пустой, остальные — с цифрами.
"""

import logging

from domains.scheduling.groups.models import Group
from domains.scheduling.groups.queries import (
    fill_percent,
    underfilled_threshold,
    with_members_count,
)

from .forecast import revenue_forecast
from .funnel import funnel
from .registry import _number, cached, compute
from .renewal_report import renewal_summary
from .risk_list import risk_list

logger = logging.getLogger(__name__)

TILES = (
    "revenue",
    "debt",
    "group_fill",
    "lead_conversion",
    "renewal_conversion",
    "risk",
    "forecast",
)


def _change(current, previous):
    """Изменение в процентных пунктах — для конверсий: «было 30%, стало
    35%» — это +5 п.п., а не +16,7%."""
    if current is None or previous is None:
        return None
    return round(float(current) - float(previous), 1)


def _metrics(scope, period):
    data = compute(["revenue", "debt_total", "group_fill"], scope, period, series=False)

    def part(name):
        metric = data[name]
        return {
            "value": metric["value"],
            "previous": metric.get("previous"),
            "change_percent": metric.get("change_percent"),
            "enough_data": metric["enough_data"],
            "days_until_enough": metric["days_until_enough"],
            "data_since": metric["data_since"],
        }

    return {
        "revenue": part("revenue"),
        "debt": part("debt_total"),
        "group_fill": part("group_fill"),
    }


def _groups(scope):
    """Места и недобор — по тем же активным группам, что group_fill."""
    groups = scope.filter(
        with_members_count(
            Group.objects.for_tenant(scope.organization).filter(status=Group.Status.ACTIVE)
        ),
        "branch_id",
    ).only("capacity", "status")
    threshold = underfilled_threshold(scope.organization)
    rows = list(groups)
    return {
        "groups": len(rows),
        "members": sum(group.members_count for group in rows),
        "capacity": sum(group.capacity or 0 for group in rows),
        "underfilled": sum(fill_percent(group) < threshold for group in rows),
        "threshold": threshold,
    }


def _lead_conversion(scope, period):
    data = funnel(scope, period)
    previous = data.get("previous") or {}
    purchased = next(s["count"] for s in data["stages"] if s["key"] == "purchased")
    return {
        "value": data["conversion"],
        "previous": previous.get("conversion"),
        "change_pp": _change(data["conversion"], previous.get("conversion")),
        "leads": data["total"],
        "purchased": purchased,
    }


def _renewal_conversion(scope, period):
    def run():
        return renewal_summary(scope, period)

    key = f"dash:renewal:{scope.cache_key}:{period.start}:{period.end}"
    data = cached(key, period, scope, run)
    previous = data["previous"] or {}
    return {
        "value": data["rate"],
        "previous": previous.get("rate"),
        "change_pp": _change(data["rate"], previous.get("rate")),
        "ended": data["ended"],
        "decided": data["decided"],
        "renewed": data["renewed"],
        "pending": data["pending"],
        "small": data["small"],
        "grace_days": data["grace_days"],
    }


def _risk(scope, period):
    def run():
        return risk_list(scope, period)["summary"]

    key = f"dash:risk:{scope.cache_key}:{period.start}:{period.end}"
    summary = cached(key, period, scope, run)
    return {
        "value": summary["total"],
        "urgent": summary["urgent"],
        "share_percent": summary["share_percent"],
        "active_children": summary["active_children"],
    }


def _forecast(scope, period):
    # Прогноз смотрит вперёд от сегодня — период ему не нужен, но кэш
    # живёт столько же, сколько у открытого периода (минуту).
    def run():
        return revenue_forecast(scope)["forecast"]

    data = cached(f"dash:forecast:{scope.cache_key}", period, scope, run)
    return {
        "month": data["month"],
        "status": data["status"],
        "value": _number(data["value"]),
        "low": _number(data["low"]),
        "high": _number(data["high"]),
        "need_more": data["need_more"],
        "expiring": data["expiring"],
    }


def _safe(name, func, *args):
    try:
        return func(*args)
    except Exception:
        logger.exception("dashboard tile %s failed", name)
        return None


def owner_dashboard(scope, period) -> dict:
    metrics = _safe("metrics", _metrics, scope, period) or {}
    group_fill = metrics.get("group_fill")
    if group_fill is not None:
        group_fill.update(_safe("groups", _groups, scope) or {})
    tiles = {
        "revenue": metrics.get("revenue"),
        "debt": metrics.get("debt"),
        "group_fill": group_fill,
        "lead_conversion": _safe("lead_conversion", _lead_conversion, scope, period),
        "renewal_conversion": _safe("renewal_conversion", _renewal_conversion, scope, period),
        "risk": _safe("risk", _risk, scope, period),
        "forecast": _safe("forecast", _forecast, scope, period),
    }
    return {"tiles": tiles}
