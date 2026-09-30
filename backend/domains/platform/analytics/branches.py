"""
Сравнение филиалов (TRU-128, ТЗ раздел 7, тариф Network).

Филиалы в строках, метрики в колонках. Каждая цифра — та же, что в отчёте
по одному филиалу: считаем реестром метрик и воронкой с выборкой ровно из
этого филиала, а не отдельной формулой.

Нормализация: филиал на 500 детей и на 80 по абсолютной выручке не
сравнить — рядом с абсолютными идут относительные (выручка и долг на
ребёнка, доли, конверсия). Ребёнок — тот, кто ходил на занятия в периоде
(«Ходили на занятия»).

Конверсия продлений и отток появятся колонками, когда будут метрики
(TRU-126 и отчёт по оттоку): колонка — строка в COLUMNS.
"""

from dataclasses import dataclass
from decimal import Decimal

from domains.platform.tenants.models import Branch

from .breakdowns import breakdown
from .funnel import funnel, funnel_by
from .registry import compute
from .scope import Scope


@dataclass(frozen=True)
class ComparisonColumn:
    key: str
    label: str
    unit: str  # money, percent, count
    # Относительная величина — её честно сравнивать между филиалами разного размера.
    relative: bool
    # Больше — лучше (выручка) или меньше — лучше (долг).
    higher_is_better: bool = True


COLUMNS = [
    ComparisonColumn("revenue_per_child", "Выручка на ребёнка", "money", True),
    ComparisonColumn("revenue", "Выручка", "money", False),
    ComparisonColumn("average_check", "Средний чек", "money", True),
    ComparisonColumn("group_fill", "Заполняемость групп", "percent", True),
    ComparisonColumn("attendance_rate", "Доля посещений", "percent", True),
    ComparisonColumn("lead_conversion", "Конверсия заявок", "percent", True),
    ComparisonColumn("debt_per_child", "Долг на ребёнка", "money", True, higher_is_better=False),
    ComparisonColumn("debt_total", "Задолженность", "money", False, higher_is_better=False),
    ComparisonColumn("active_children", "Ходили на занятия", "count", False),
    ComparisonColumn("new_leads", "Новых заявок", "count", False),
]
COLUMN_KEYS = [column.key for column in COLUMNS]
# Метрики реестра, из которых собираются колонки.
BASE = [
    "revenue",
    "average_check",
    "group_fill",
    "attendance_rate",
    "debt_total",
    "active_children",
    "new_leads",
]


def _decimal(value):
    return None if value in (None, "") else Decimal(str(value))


def _per(value, children):
    if value is None or not children:
        return None
    return round(value / children)


def _row(scope, period):
    data = compute(BASE, scope, period, series=False)
    current = {name: _decimal(data[name]["value"]) for name in BASE}
    previous = {name: _decimal(data[name].get("previous")) for name in BASE}
    conversion = funnel(scope, period, compare=True)
    values = {
        **current,
        "revenue_per_child": _per(current["revenue"], current["active_children"]),
        "debt_per_child": _per(current["debt_total"], current["active_children"]),
        "lead_conversion": _decimal(conversion["conversion"]),
    }
    before = {
        **previous,
        "revenue_per_child": _per(previous["revenue"], previous["active_children"]),
        # Долг — снимок «сейчас», прошлого на ребёнка из него не собрать.
        "debt_per_child": None,
        "lead_conversion": _decimal(conversion["previous"]["conversion"]),
    }
    return {
        key: {
            "value": _str(values.get(key)),
            "previous": _str(before.get(key)),
        }
        for key in COLUMN_KEYS
    }


def _str(value):
    if value is None:
        return None
    value = Decimal(value)
    return str(int(value)) if value == value.to_integral() else f"{value:f}"


def _ratio(top, bottom, scale=1):
    # Та же формула, что RatioMetric: средний чек, доля посещений.
    if top is None or not bottom:
        return None
    return round(Decimal(top) * scale / Decimal(bottom), 1)


def _grouped(scope, period):
    """Значения всех филиалов разом: по одному сгруппированному запросу на
    метрику (разбивка «по филиалу»), а не 7 метрик × N филиалов."""
    by = {}
    for name in (
        "revenue",
        "payments_count",
        "visits",
        "attendance_marks",
        "new_leads",
        "active_children",
    ):
        by[name] = {
            item["key"]: _decimal(item["value"])
            for item in breakdown(name, "branch", scope, period)
        }
    conversion = {
        item["key"]: _decimal(item["conversion"]) for item in funnel_by(scope, period, "branch")
    }
    return by, conversion


def _branch_values(branch_id, by, conversion):
    get = lambda name: by[name].get(branch_id)  # noqa: E731
    revenue, children = get("revenue") or Decimal(0), get("active_children")
    return {
        "revenue": revenue,
        "average_check": _ratio(get("revenue"), get("payments_count")),
        "attendance_rate": _ratio(get("visits"), get("attendance_marks"), 100),
        "active_children": children or Decimal(0),
        "new_leads": get("new_leads") or Decimal(0),
        "revenue_per_child": _per(revenue, children),
        "lead_conversion": conversion.get(branch_id),
    }


def compare_branches(scope, period):
    """{"columns": [...], "rows": [{branch, values}], "total": {...},
    "comparable": bool}. Выборка филиалов — из scope (права управляющего)."""
    branches = (
        list(scope.branches)
        if scope.branch_ids is not None
        else list(
            Branch.objects.for_tenant(scope.organization).filter(is_active=True).order_by("name")
        )
    )
    now, now_conv = _grouped(scope, period)
    before, before_conv = _grouped(scope, period.previous())
    rows = []
    for branch in branches:
        key = str(branch.pk)
        current = _branch_values(key, now, now_conv)
        previous = _branch_values(key, before, before_conv)
        # Снимки «на сейчас» — из тех же сервисов, по одному филиалу (дёшево).
        snapshot = compute(
            ["group_fill", "debt_total"],
            Scope(scope.organization, (branch.pk,), [branch]),
            period,
            series=False,
        )
        current["group_fill"] = _decimal(snapshot["group_fill"]["value"])
        current["debt_total"] = _decimal(snapshot["debt_total"]["value"])
        current["debt_per_child"] = _per(current["debt_total"], current["active_children"])
        previous["group_fill"] = _decimal(snapshot["group_fill"].get("previous"))
        previous["debt_total"] = _decimal(snapshot["debt_total"].get("previous"))
        previous["debt_per_child"] = None
        rows.append(
            {
                "branch": {"id": key, "name": branch.name},
                "values": {
                    k: {"value": _str(current.get(k)), "previous": _str(previous.get(k))}
                    for k in COLUMN_KEYS
                },
            }
        )
    return {
        "columns": [
            {
                "key": c.key,
                "label": c.label,
                "unit": c.unit,
                "relative": c.relative,
                "higher_is_better": c.higher_is_better,
            }
            for c in COLUMNS
        ],
        "rows": rows,
        # Итог по выборке — как «вся организация» или «мои филиалы».
        "total": _row(scope, period),
        "comparable": len(rows) > 1,
    }


def branch_trends(scope, period, metric):
    """Динамика одной метрики по каждому филиалу — линии на одном графике."""
    branches = (
        list(scope.branches)
        if scope.branch_ids is not None
        else list(
            Branch.objects.for_tenant(scope.organization).filter(is_active=True).order_by("name")
        )
    )
    result = []
    for branch in branches:
        data = compute([metric], Scope(scope.organization, (branch.pk,), [branch]), period)[metric]
        result.append(
            {
                "branch": {"id": str(branch.pk), "name": branch.name},
                "unit": data["unit"],
                "series": data.get("series") or [],
            }
        )
    return result
