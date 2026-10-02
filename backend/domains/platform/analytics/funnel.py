"""
Конверсия воронки продаж по этапам (TRU-115, ТЗ п. 5.3):
заявка → связались → записан на пробное → пришёл на пробное → купил.

Считаем когортой: берём новые заявки, созданные за период (продления —
отдельная воронка, TRU-98, сюда не попадают), и по истории статусов
(TRU-99) смотрим, до какого этапа дошла каждая. Поэтому прошлый период
можно пересчитать в любой момент, а цифра за закрытый месяц со временем
только растёт — заявки ещё дозревают.

Этап засчитан, если заявка в нём была или прошла дальше, откуда в него
нельзя не попасть: записанный на пробное точно был на связи. Купить без
пробного можно — такие покупки считаются отдельно, иначе «пришёл на
пробное → купил» показывало бы больше 100%.
"""

from collections import Counter, defaultdict

from domains.platform.leads.models import Lead, LeadKind, LeadStatusChange
from domains.platform.users.models import User

from .breakdowns import DIMENSIONS
from .registry import cached

S = Lead.Status
STAGES = [S.NEW, S.CONTACTED, S.TRIAL_SCHEDULED, S.TRIAL_ATTENDED, S.PURCHASED]
# Какие статусы означают, что этап пройден.
REACHED = {
    S.NEW: None,  # любая заявка когорты
    S.CONTACTED: {S.CONTACTED, S.THINKING, S.TRIAL_SCHEDULED, S.TRIAL_ATTENDED, S.PURCHASED},
    S.TRIAL_SCHEDULED: {S.TRIAL_SCHEDULED, S.TRIAL_ATTENDED},
    S.TRIAL_ATTENDED: {S.TRIAL_ATTENDED},
    S.PURCHASED: {S.PURCHASED},
}
FILTERS = {"source": "source_id", "direction": "direction_id", "manager": "assigned_to_id"}
BY = {
    "source": "source_id",
    "direction": "direction_id",
    "branch": "branch_id",
    "manager": "assigned_to_id",
}


class FunnelError(ValueError):
    pass


def cohort(scope, period, filters=None):
    """Новые заявки, созданные за период, в выборке филиалов и фильтрах."""
    start, end = period.bounds(scope.organization)
    qs = Lead.objects.for_tenant(scope.organization).filter(
        kind=LeadKind.NEW, created_at__gte=start, created_at__lt=end
    )
    qs = scope.filter(qs, "branch_id")
    for name, field in FILTERS.items():
        value = (filters or {}).get(name)
        if value:
            qs = qs.filter(**{field: value})
    return qs.order_by()


def _stage_counts(rows, history):
    """rows — [(id, текущий статус)], history — {id: {статусы}}."""
    counts = Counter()
    purchased_after_trial = 0
    for lead_id, status in rows:
        seen = history.get(lead_id, set()) | {status}
        for stage in STAGES:
            if REACHED[stage] is None or seen & REACHED[stage]:
                counts[stage] += 1
        if S.PURCHASED in seen and S.TRIAL_ATTENDED in seen:
            purchased_after_trial += 1
    return counts, purchased_after_trial


def _history(lead_ids):
    history = defaultdict(set)
    rows = (
        LeadStatusChange.objects.filter(lead_id__in=lead_ids)
        .values_list("lead_id", "to_status")
        .distinct()
    )
    for lead_id, status in rows:
        history[lead_id].add(status)
    return history


def _summary(rows, history):
    counts, after_trial = _stage_counts(rows, history)
    current = Counter(status for _, status in rows)
    total = counts[S.NEW]
    return {
        "total": total,
        "stages": [
            {
                "key": stage,
                "label": S(stage).label,
                "count": counts[stage],
                # Сейчас стоят на этом этапе — «застрявшие», по клику открываются.
                "current": current[stage],
            }
            for stage in STAGES
        ],
        "purchased_after_trial": after_trial,
        "purchased_without_trial": counts[S.PURCHASED] - after_trial,
        "thinking": current[S.THINKING],
        "rejected": current[S.REJECTED],
        "conversion": round(counts[S.PURCHASED] * 100 / total, 1) if total else None,
    }


def _key(scope, period, filters):
    return f"{scope.cache_key}:{period.start}:{period.end}:{sorted((filters or {}).items())}"


def funnel(scope, period, filters=None, compare=True):
    def run():
        rows = list(cohort(scope, period, filters).values_list("id", "status"))
        result = _summary(rows, _history([lead_id for lead_id, _ in rows]))
        if compare:
            previous = period.previous()
            prev_rows = list(cohort(scope, previous, filters).values_list("id", "status"))
            result["previous"] = _summary(prev_rows, _history([i for i, _ in prev_rows]))
        return result

    key = f"f:{_key(scope, period, filters)}:{compare}"
    return cached(key, period, scope, run)


def _labels(organization, dimension, keys):
    if dimension == "manager":
        users = User.objects.filter(organization=organization, pk__in=[k for k in keys if k])
        return {user.pk: user.full_name for user in users}
    return DIMENSIONS[dimension](organization, keys)


def funnel_by(scope, period, dimension, filters=None):
    """Та же воронка, разложенная по источнику, направлению, филиалу или
    ответственному: строки таблицы «где теряем»."""
    if dimension not in BY:
        raise FunnelError("Разрез: source, direction, branch или manager.")

    def run():
        field = BY[dimension]
        rows = list(cohort(scope, period, filters).values_list("id", "status", field))
        history = _history([lead_id for lead_id, _, _ in rows])
        groups = defaultdict(list)
        for lead_id, status, key in rows:
            groups[key].append((lead_id, status))
        labels = _labels(scope.organization, dimension, list(groups))
        items = []
        for key, group_rows in groups.items():
            summary = _summary(group_rows, history)
            items.append(
                {
                    "key": str(key) if key else None,
                    "label": labels.get(key) if key else None,
                    "total": summary["total"],
                    "stages": {stage["key"]: stage["count"] for stage in summary["stages"]},
                    "conversion": summary["conversion"],
                }
            )
        # Больше заявок — выше; при равенстве — лучшая конверсия, «не указано» — в конце.
        return sorted(
            items,
            key=lambda item: (
                -item["total"],
                -(item["conversion"] or 0),
                item["label"] is None,
                item["label"] or "",
            ),
        )

    key = f"fb:{dimension}:{_key(scope, period, filters)}"
    return cached(key, period, scope, run)
