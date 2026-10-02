"""Переиспользуемая выборка загрузки преподавателей (TRU-120).

Источник — занятия расписания, а не отметки посещаемости: эти же строки
позже можно использовать как основу начислений. Отчёт описывает объём
нагрузки и отмены, но намеренно не вычисляет «эффективность» преподавателя.
"""

import calendar
from collections import defaultdict
from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db.models import Prefetch, Q

from domains.platform.tenants.models import Direction
from domains.platform.users.models import User
from domains.scheduling.groups.models import GroupMembership
from domains.scheduling.schedule.models import Lesson, LessonEnrollment

COUNTED_STATUSES = (Lesson.Status.SCHEDULED, Lesson.Status.COMPLETED, Lesson.Status.CANCELLED)
TEACHER_CANCEL_REASONS = {Lesson.CancelReasonCategory.TEACHER_ILLNESS}


def _percent(part, whole):
    return round(Decimal(part) * 100 / Decimal(whole), 1) if whole else None


def _monthly_points(period):
    current = period.start.replace(day=1)
    points = []
    while current <= period.end:
        last = date(
            current.year, current.month, calendar.monthrange(current.year, current.month)[1]
        )
        points.append((current, min(last, period.end)))
        current = (current.replace(day=28) + date.resolution * 4).replace(day=1)
    return points


def _lesson_branch_id(lesson):
    return (
        lesson.group.branch_id
        if lesson.group_id
        else lesson.room.branch_id
        if lesson.room_id
        else None
    )


def _participant_ids(lesson, timezone):
    """Состав именно на дату занятия, включая индивидуальных и записи поверх."""
    day = lesson.starts_at.astimezone(timezone).date()
    if lesson.group_id:
        ids = {
            membership.child_id
            for membership in lesson.group.memberships.all()
            if membership.joined_at <= day
            and (membership.left_at is None or membership.left_at > day)
        }
    else:
        ids = {child.id for child in lesson.individual_children.all()}
    ids.update(
        enrollment.child_id
        for enrollment in lesson.enrollments.all()
        if enrollment.created_at <= lesson.ends_at
        and (enrollment.cancelled_at is None or enrollment.cancelled_at >= lesson.starts_at)
    )
    return ids


def lessons_for_workload(scope, period, *, direction_id=None):
    """Занятия отчёта; публичная функция для будущего расчёта зарплат."""
    start, end = period.bounds(scope.organization)
    memberships = GroupMembership.objects.select_related("child").order_by("joined_at")
    enrollments = LessonEnrollment.objects.select_related("child").order_by("created_at")
    queryset = (
        Lesson.objects.for_tenant(scope.organization)
        .filter(
            teacher__isnull=False,
            starts_at__gte=start,
            starts_at__lt=end,
            status__in=COUNTED_STATUSES,
        )
        .select_related("teacher", "group__branch", "group__direction", "room__branch")
        .prefetch_related(
            "individual_children",
            Prefetch("group__memberships", queryset=memberships),
            Prefetch("enrollments", queryset=enrollments),
        )
        .order_by("starts_at", "teacher__full_name")
    )
    if scope.branch_ids is not None:
        queryset = queryset.filter(
            Q(group__branch_id__in=scope.branch_ids) | Q(room__branch_id__in=scope.branch_ids)
        )
    if direction_id:
        queryset = queryset.filter(group__direction_id=direction_id)
    return queryset


def _empty_teacher(teacher):
    return {
        "id": str(teacher.id),
        "name": teacher.full_name,
        "planned": 0,
        "completed": 0,
        "scheduled": 0,
        "cancelled": 0,
        "teacher_cancelled": 0,
        "student_ids": set(),
        "fill_occupied": 0,
        "fill_capacity": 0,
        "cancel_reasons": defaultdict(int),
        "lessons": [],
    }


def _add_lesson(row, lesson, participant_ids):
    row["planned"] += 1
    row["lessons"].append(lesson)
    if lesson.status == Lesson.Status.COMPLETED:
        row["completed"] += 1
    elif lesson.status == Lesson.Status.CANCELLED:
        row["cancelled"] += 1
        reason = lesson.cancel_reason_category or "not_set"
        row["cancel_reasons"][reason] += 1
        if reason in TEACHER_CANCEL_REASONS:
            row["teacher_cancelled"] += 1
    else:
        row["scheduled"] += 1

    if lesson.status != Lesson.Status.CANCELLED:
        row["student_ids"].update(participant_ids)
        if lesson.group_id and lesson.group.capacity:
            row["fill_occupied"] += len(participant_ids)
            row["fill_capacity"] += lesson.group.capacity


def _serialize_teacher(row, days):
    weeks = Decimal(days) / Decimal(7)
    return {
        "id": row["id"],
        "name": row["name"],
        "lessons_per_week": round(Decimal(row["planned"]) / weeks, 1) if weeks else 0,
        "planned": row["planned"],
        "completed": row["completed"],
        "scheduled": row["scheduled"],
        "cancelled": row["cancelled"],
        "teacher_cancelled": row["teacher_cancelled"],
        "students": len(row["student_ids"]),
        "fill_percent": _percent(row["fill_occupied"], row["fill_capacity"]),
        "cancel_reasons": [
            {
                "key": key,
                "label": dict(Lesson.CancelReasonCategory.choices).get(key, "Не указана"),
                "value": value,
                "teacher_fault": key in TEACHER_CANCEL_REASONS,
            }
            for key, value in sorted(row["cancel_reasons"].items(), key=lambda item: -item[1])
        ],
    }


def _breakdown(lessons, participants, key, labels):
    rows = {}
    for lesson in lessons:
        value = key(lesson)
        if value not in rows:
            rows[value] = {
                "teachers": set(),
                "students": set(),
                "planned": 0,
                "completed": 0,
                "cancelled": 0,
            }
        row = rows[value]
        row["teachers"].add(lesson.teacher_id)
        row["planned"] += 1
        row["completed"] += lesson.status == Lesson.Status.COMPLETED
        row["cancelled"] += lesson.status == Lesson.Status.CANCELLED
        if lesson.status != Lesson.Status.CANCELLED:
            row["students"].update(participants[lesson.id])
    return [
        {
            "key": str(key_value) if key_value else None,
            "label": labels.get(key_value, "Не указано"),
            "teachers": len(row["teachers"]),
            "students": len(row["students"]),
            "planned": row["planned"],
            "completed": row["completed"],
            "cancelled": row["cancelled"],
        }
        for key_value, row in sorted(
            rows.items(), key=lambda item: (-item[1]["planned"], str(item[0]))
        )
    ]


def teacher_workload(scope, period, params=None):
    params = params or {}
    direction_id = params.get("direction") or None
    selected_teacher = str(params.get("teacher") or "")
    lessons = list(lessons_for_workload(scope, period, direction_id=direction_id))
    timezone = ZoneInfo(scope.organization.timezone)
    participants = {lesson.id: _participant_ids(lesson, timezone) for lesson in lessons}

    teacher_query = User.objects.filter(
        organization=scope.organization,
        role=User.Role.TEACHER,
        is_active=True,
    )
    if selected_teacher:
        teacher_query = teacher_query.filter(pk=selected_teacher)
        lessons = [lesson for lesson in lessons if str(lesson.teacher_id) == selected_teacher]
    elif direction_id:
        teacher_ids = {lesson.teacher_id for lesson in lessons}
        teacher_query = teacher_query.filter(pk__in=teacher_ids)
    elif scope.branch_ids is not None:
        lesson_teacher_ids = {lesson.teacher_id for lesson in lessons}
        teacher_query = teacher_query.filter(
            Q(branches__id__in=scope.branch_ids) | Q(pk__in=lesson_teacher_ids)
        ).distinct()

    teacher_rows = {
        teacher.id: _empty_teacher(teacher) for teacher in teacher_query.order_by("full_name")
    }
    for lesson in lessons:
        row = teacher_rows.setdefault(lesson.teacher_id, _empty_teacher(lesson.teacher))
        _add_lesson(row, lesson, participants[lesson.id])

    serialized = []
    for row in teacher_rows.values():
        teacher = _serialize_teacher(row, period.days)
        trend = []
        for month_start, month_end in _monthly_points(period):
            month_row = {
                **row,
                "planned": 0,
                "completed": 0,
                "scheduled": 0,
                "cancelled": 0,
                "teacher_cancelled": 0,
                "student_ids": set(),
                "fill_occupied": 0,
                "fill_capacity": 0,
                "cancel_reasons": defaultdict(int),
                "lessons": [],
            }
            for lesson in row["lessons"]:
                local_day = lesson.starts_at.astimezone(timezone).date()
                if month_start <= local_day <= month_end:
                    _add_lesson(month_row, lesson, participants[lesson.id])
            point = _serialize_teacher(month_row, (month_end - month_start).days + 1)
            trend.append(
                {
                    "date": month_start.isoformat(),
                    **{
                        k: point[k]
                        for k in ("planned", "completed", "cancelled", "students", "fill_percent")
                    },
                }
            )
        teacher["trend"] = trend
        serialized.append(teacher)
    serialized.sort(key=lambda row: (-row["lessons_per_week"], row["name"]))

    branch_labels = {
        lesson.group.branch_id if lesson.group_id else lesson.room.branch_id: (
            lesson.group.branch.name if lesson.group_id else lesson.room.branch.name
        )
        for lesson in lessons
        if lesson.group_id or lesson.room_id
    }
    direction_labels = {
        lesson.group.direction_id: lesson.group.direction.name
        for lesson in lessons
        if lesson.group_id
    }
    reasons = defaultdict(int)
    for lesson in lessons:
        if lesson.status == Lesson.Status.CANCELLED:
            reasons[lesson.cancel_reason_category or "not_set"] += 1

    return {
        "period": period.as_dict(),
        "summary": {
            "teachers": len(serialized),
            "planned": sum(row["planned"] for row in serialized),
            "completed": sum(row["completed"] for row in serialized),
            "cancelled": sum(row["cancelled"] for row in serialized),
            "teacher_cancelled": sum(row["teacher_cancelled"] for row in serialized),
            "students": len(
                set().union(
                    *(teacher_rows[teacher_id]["student_ids"] for teacher_id in teacher_rows)
                )
            )
            if teacher_rows
            else 0,
        },
        "teachers": serialized,
        "breakdowns": {
            "branch": _breakdown(lessons, participants, _lesson_branch_id, branch_labels),
            "direction": _breakdown(
                lessons,
                participants,
                lambda lesson: lesson.group.direction_id if lesson.group_id else None,
                direction_labels,
            ),
        },
        "cancel_reasons": [
            {
                "key": key,
                "label": dict(Lesson.CancelReasonCategory.choices).get(key, "Не указана"),
                "value": value,
                "teacher_fault": key in TEACHER_CANCEL_REASONS,
            }
            for key, value in sorted(reasons.items(), key=lambda item: -item[1])
        ],
        "filters": {
            "teachers": [
                {"id": str(teacher.id), "name": teacher.full_name}
                for teacher in User.objects.filter(
                    organization=scope.organization,
                    role=User.Role.TEACHER,
                    is_active=True,
                ).order_by("full_name")
            ],
            "directions": [
                {"id": str(direction.id), "name": direction.name}
                for direction in Direction.objects.for_tenant(scope.organization)
                .filter(is_active=True)
                .order_by("name")
            ],
        },
    }
