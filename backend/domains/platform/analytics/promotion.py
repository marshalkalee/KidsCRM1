"""Сигналы продвижения групп (TRU-161), без персональных данных."""

import hashlib
from collections import Counter, defaultdict

from domains.platform.leads.models import Lead, LeadKind
from domains.scheduling.groups.models import Group

from .group_occupancy import group_occupancy
from .period import Period, _add_months


def _lead_rows(scope, period):
    start, end = period.bounds(scope.organization)
    queryset = Lead.objects.for_tenant(scope.organization).filter(
        kind=LeadKind.NEW,
        created_at__gte=start,
        created_at__lt=end,
    )
    queryset = scope.filter(queryset, "branch_id")
    return list(
        queryset.values(
            "branch_id",
            "direction_id",
            "child_age",
            "source__name",
            "status",
        )
    )


def _last_year(period):
    return Period(_add_months(period.start, -12), _add_months(period.end, -12), "custom")


def _percent(part, whole):
    return round(part * 100 / whole, 1) if whole else None


def _season(month):
    if month in {5, 6}:
        return "конец учебного сезона"
    if month in {7, 8}:
        return "лето и подготовка к набору"
    if month in {9, 10}:
        return "высокий сезон набора"
    return "обычный сезон"


def _key(row):
    raw = "|".join((row["branch"], row["direction"], row["name"]))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def promotion_signals(scope, period):
    """Аргументы по каждой недозаполненной группе и системные срезы."""
    occupancy = group_occupancy(scope, period)
    group_ids = [row["id"] for row in occupancy["underfilled"]]
    groups = {
        str(group.id): group
        for group in Group.objects.for_tenant(scope.organization)
        .filter(pk__in=group_ids, exclude_from_ai_recommendations=False)
        .only("id", "branch_id", "direction_id", "age_min", "age_max")
    }
    current = _lead_rows(scope, period)
    previous = _lead_rows(scope, _last_year(period))

    totals = defaultdict(lambda: {"all": 0, "underfilled": 0})
    for row in occupancy["groups"]:
        bucket = totals[(row["branch"], row["direction"])]
        bucket["all"] += 1
        bucket["underfilled"] += int(row["is_underfilled"])

    candidates = []
    for row in occupancy["underfilled"]:
        group = groups.get(row["id"])
        if group is None:
            continue
        matching = [
            lead
            for lead in current
            if lead["branch_id"] == group.branch_id and lead["direction_id"] == group.direction_id
        ]
        purchased = sum(lead["status"] == Lead.Status.PURCHASED for lead in matching)
        age_matching = [
            lead
            for lead in matching
            if lead["child_age"] is not None
            and (group.age_min is None or lead["child_age"] >= group.age_min)
            and (group.age_max is None or lead["child_age"] <= group.age_max)
        ]
        source_counts = Counter(lead["source__name"] or "Не указан" for lead in age_matching)
        top_sources = [
            {"источник": name, "заявок": count} for name, count in source_counts.most_common(3)
        ]
        previous_count = sum(
            lead["branch_id"] == group.branch_id and lead["direction_id"] == group.direction_id
            for lead in previous
        )
        available = max(0, (row["capacity"] or 0) - row["occupied"])
        demand_case = "quick_win" if matching else "build_demand"
        section = totals[(row["branch"], row["direction"])]
        systemic = section["all"] > 1 and section["all"] == section["underfilled"]
        candidates.append(
            {
                "candidate_key": _key(row),
                "группа": row["name"],
                "филиал": row["branch"],
                "направление": row["direction"],
                "возраст_от": group.age_min,
                "возраст_до": group.age_max,
                "свободных_мест": available,
                "занято": row["occupied"],
                "вместимость": row["capacity"],
                "заполняемость_процент": row["percent"],
                "заявок_на_направление": len(matching),
                "купили": purchased,
                "конверсия_процент": _percent(purchased, len(matching)),
                "источники_этого_возраста": top_sources,
                "заявок_в_тот_же_месяц_год_назад": previous_count,
                "сезон": _season(period.end.month),
                "случай": demand_case,
                "системная_проблема_направления_в_филиале": systemic,
                "приоритет": available * (2 if demand_case == "quick_win" else 1),
            }
        )
    candidates.sort(
        key=lambda item: (
            item["случай"] != "quick_win",
            -item["приоритет"],
            item["филиал"],
            item["группа"],
        )
    )
    return {
        "период": period.as_dict(),
        "сезон": _season(period.end.month),
        "кандидаты": candidates,
    }
