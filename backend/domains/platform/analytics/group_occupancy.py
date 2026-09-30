"""Отчёт по заполняемости групп (TRU-119).

Текущие значения берутся через ``groups.queries`` — тот же источник,
который обслуживает список групп. История восстанавливается по датам
вступления и выхода из состава; отдельной конкурирующей формулы для
текущей заполняемости здесь нет.
"""

import calendar
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import Prefetch, Q

from domains.platform.users.models import User
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.groups.queries import (
    active_template,
    fill_percent,
    is_underfilled,
    underfilled_threshold,
    with_members_count,
)
from domains.scheduling.schedule_templates.models import ScheduleTemplate

WEEKDAYS = [
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
]
TIME_BUCKETS = {
    "morning": ("Утро", lambda hour: hour < 12),
    "day": ("Днём", lambda hour: 12 <= hour < 17),
    "evening": ("Вечер", lambda hour: hour >= 17),
}


def _percent(occupied, capacity):
    return round(Decimal(occupied) * 100 / Decimal(capacity), 1) if capacity else None


def _slot_data(group):
    template = active_template(group)
    if not template:
        return []
    return [
        {
            "weekday": slot.weekday,
            "start_time": slot.start_time,
            "teacher_id": slot.teacher_id,
        }
        for slot in template.slots.all()
    ]


def _time_bucket(hour):
    return next(key for key, (_label, matches) in TIME_BUCKETS.items() if matches(hour))


def _month_points(period):
    current = period.start.replace(day=1)
    points = []
    while current <= period.end:
        last = date(
            current.year, current.month, calendar.monthrange(current.year, current.month)[1]
        )
        points.append(min(last, period.end))
        current = (current.replace(day=28) + date.resolution * 4).replace(day=1)
    return points


def _trend(groups, period, organization):
    points = _month_points(period)
    if not groups:
        return [
            {"date": point.isoformat(), "value": None, "occupied": 0, "capacity": 0}
            for point in points
        ]
    memberships = list(
        GroupMembership.objects.for_tenant(organization)
        .filter(group_id__in=[group.id for group in groups], joined_at__lte=period.end)
        .filter(Q(left_at__isnull=True) | Q(left_at__gt=period.start))
        .values("group_id", "joined_at", "left_at")
    )
    created = {group.id: group.created_at.date() for group in groups}
    capacity = {group.id: group.capacity or 0 for group in groups}
    result = []
    for point in points:
        available_groups = {group.id for group in groups if created[group.id] <= point}
        occupied = sum(
            1
            for membership in memberships
            if membership["group_id"] in available_groups
            and membership["joined_at"] <= point
            and (membership["left_at"] is None or membership["left_at"] > point)
        )
        total_capacity = sum(capacity[group_id] for group_id in available_groups)
        result.append(
            {
                "date": point.isoformat(),
                "value": _percent(occupied, total_capacity),
                "occupied": occupied,
                "capacity": total_capacity,
            }
        )
    return result


def _aggregate(groups, key, labels):
    values = defaultdict(lambda: {"occupied": 0, "capacity": 0, "groups": set()})
    for group in groups:
        for item in key(group):
            row = values[item]
            row["occupied"] += group.members_count
            row["capacity"] += group.capacity or 0
            row["groups"].add(group.id)
    return [
        {
            "key": str(item),
            "label": labels.get(item, str(item)),
            "occupied": row["occupied"],
            "capacity": row["capacity"],
            "groups_count": len(row["groups"]),
            "value": _percent(row["occupied"], row["capacity"]),
        }
        for item, row in values.items()
    ]


def _merge_candidates(group, groups):
    own = {(slot["weekday"], slot["start_time"]) for slot in group._analytics_slots}
    candidates = []
    for other in groups:
        if (
            other.id == group.id
            or other.branch_id != group.branch_id
            or other.direction_id != group.direction_id
            or group.members_count + other.members_count > max(group.capacity, other.capacity)
        ):
            continue
        compatible = any(
            weekday == other_slot["weekday"]
            and abs(
                start.hour * 60
                + start.minute
                - other_slot["start_time"].hour * 60
                - other_slot["start_time"].minute
            )
            <= 120
            for weekday, start in own
            for other_slot in other._analytics_slots
        )
        if compatible:
            candidates.append({"id": str(other.id), "name": other.name})
    return candidates


def group_occupancy(scope, period, params=None):
    params = params or {}
    templates = ScheduleTemplate.objects.prefetch_related("slots").order_by("-valid_from")
    groups = list(
        scope.filter(
            with_members_count(
                Group.objects.for_tenant(scope.organization)
                .filter(status=Group.Status.ACTIVE)
                .select_related("branch", "direction")
                .prefetch_related("teachers", Prefetch("schedule_templates", queryset=templates))
            ),
            "branch_id",
        ).order_by("branch__name", "name")
    )
    for group in groups:
        group._analytics_slots = _slot_data(group)
        group._analytics_teacher_ids = {teacher.id for teacher in group.teachers.all()} | {
            slot["teacher_id"] for slot in group._analytics_slots if slot["teacher_id"]
        }

    base_groups = groups
    direction = str(params.get("direction") or "")
    teacher = str(params.get("teacher") or "")
    weekday = str(params.get("weekday") or "")
    time_bucket = str(params.get("time") or "")
    if direction:
        groups = [group for group in groups if str(group.direction_id) == direction]
    if teacher:
        groups = [
            group for group in groups if teacher in {str(pk) for pk in group._analytics_teacher_ids}
        ]
    if weekday.isdigit():
        groups = [
            group
            for group in groups
            if any(slot["weekday"] == int(weekday) for slot in group._analytics_slots)
        ]
    if time_bucket in TIME_BUCKETS:
        groups = [
            group
            for group in groups
            if any(
                _time_bucket(slot["start_time"].hour) == time_bucket
                for slot in group._analytics_slots
            )
        ]

    threshold = underfilled_threshold(scope.organization)
    occupied = sum(group.members_count for group in groups)
    capacity = sum(group.capacity or 0 for group in groups)
    underfilled = [group for group in groups if is_underfilled(group, threshold)]

    teacher_labels = {
        teacher.id: teacher.full_name for group in base_groups for teacher in group.teachers.all()
    }
    missing_teacher_ids = {
        pk
        for group in base_groups
        for pk in group._analytics_teacher_ids
        if pk not in teacher_labels
    }
    teacher_labels.update(
        User.objects.filter(
            organization=scope.organization, pk__in=missing_teacher_ids
        ).values_list("id", "full_name")
    )

    rows = []
    for group in groups:
        merge_candidates = _merge_candidates(group, base_groups) if group in underfilled else []
        rows.append(
            {
                "id": str(group.id),
                "name": group.name,
                "branch": group.branch.name,
                "direction": group.direction.name,
                "occupied": group.members_count,
                "capacity": group.capacity,
                "percent": fill_percent(group),
                "is_underfilled": group in underfilled,
                "suggested_action": "merge" if merge_candidates else "promotion",
                "merge_candidates": merge_candidates,
            }
        )

    branch_labels = {group.branch_id: group.branch.name for group in groups}
    direction_labels = {group.direction_id: group.direction.name for group in groups}
    weekday_labels = {index: label for index, label in enumerate(WEEKDAYS)}
    time_labels = {key: label for key, (label, _matches) in TIME_BUCKETS.items()}
    breakdowns = {
        "branch": _aggregate(groups, lambda group: [group.branch_id], branch_labels),
        "direction": _aggregate(groups, lambda group: [group.direction_id], direction_labels),
        "teacher": _aggregate(groups, lambda group: group._analytics_teacher_ids, teacher_labels),
        "weekday": _aggregate(
            groups,
            lambda group: sorted({slot["weekday"] for slot in group._analytics_slots}),
            weekday_labels,
        ),
        "time": _aggregate(
            groups,
            lambda group: sorted(
                {_time_bucket(slot["start_time"].hour) for slot in group._analytics_slots}
            ),
            time_labels,
        ),
    }
    for items in breakdowns.values():
        items.sort(key=lambda item: (item["value"] is None, -(item["value"] or 0), item["label"]))

    return {
        "period": period.as_dict(),
        "threshold": threshold,
        "summary": {
            "groups_count": len(groups),
            "occupied": occupied,
            "capacity": capacity,
            "percent": _percent(occupied, capacity),
            "underfilled_count": len(underfilled),
        },
        "groups": rows,
        "underfilled": [row for row in rows if row["is_underfilled"]],
        "trend": _trend(groups, period, scope.organization),
        "breakdowns": breakdowns,
        "filters": {
            "directions": sorted(
                (
                    {"id": str(pk), "name": name}
                    for pk, name in {
                        group.direction_id: group.direction.name for group in base_groups
                    }.items()
                ),
                key=lambda item: item["name"],
            ),
            "teachers": sorted(
                ({"id": str(pk), "name": name} for pk, name in teacher_labels.items()),
                key=lambda item: item["name"],
            ),
            "weekdays": [{"id": str(index), "name": label} for index, label in enumerate(WEEKDAYS)],
            "times": [{"id": key, "name": label} for key, label in time_labels.items()],
        },
    }
