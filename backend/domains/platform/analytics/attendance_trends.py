"""Динамика посещаемости и личная норма ребёнка (TRU-121).

Экран, Excel и будущий риск-лист используют одну выборку. Личная норма —
доля пропусков ребёнка за 8 недель перед выбранным периодом; наружу
отдаётся само отклонение, а не жёсткий общий порог риска.
"""

from datetime import timedelta
from decimal import Decimal

import pytz
from django.db.models import Count, F, Q
from django.db.models.functions import Coalesce, ExtractIsoWeekDay, TruncWeek

from domains.platform.tenants.models import Branch, Direction
from domains.platform.users.models import User
from domains.scheduling.attendance.models import Attendance
from domains.scheduling.groups.models import Group
from domains.scheduling.schedule.models import Lesson

from .period import Period

BASELINE_DAYS = 56
MIN_BASELINE_MARKS = 4
VISITED = (Attendance.Status.PRESENT, Attendance.Status.MAKEUP)
WEEKDAYS = [
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
]


def _percent(part, total):
    return round(Decimal(part) * 100 / Decimal(total), 1) if total else None


def _scoped_marks(scope):
    queryset = Attendance.objects.for_tenant(scope.organization).filter(
        lesson__organization=scope.organization,
        lesson__deleted_at__isnull=True,
    )
    if scope.branch_ids is not None:
        queryset = queryset.filter(
            Q(lesson__group__branch_id__in=scope.branch_ids)
            | Q(lesson__group__isnull=True, lesson__room__branch_id__in=scope.branch_ids)
        )
    return queryset


def _scoped_lessons(scope):
    queryset = Lesson.objects.for_tenant(scope.organization).filter(deleted_at__isnull=True)
    if scope.branch_ids is not None:
        queryset = queryset.filter(
            Q(group__branch_id__in=scope.branch_ids)
            | Q(group__isnull=True, room__branch_id__in=scope.branch_ids)
        )
    return queryset


def _in_period(queryset, field, period, organization):
    start, end = period.bounds(organization)
    return queryset.filter(**{f"{field}__gte": start, f"{field}__lt": end})


def _totals(marks):
    return marks.aggregate(
        marked=Count("id"),
        attended=Count("id", filter=Q(status__in=VISITED)),
        absences=Count("id", filter=Q(status=Attendance.Status.ABSENT)),
    )


def _held_lessons(scope, period):
    return _in_period(
        _scoped_lessons(scope).filter(status=Lesson.Status.COMPLETED),
        "starts_at",
        period,
        scope.organization,
    )


def _labels(model, organization, keys, field="name"):
    return dict(
        model.objects.for_tenant(organization)
        .filter(pk__in=[key for key in keys if key])
        .values_list("pk", field)
    )


def _staff_labels(organization, keys):
    return dict(
        User.objects.filter(
            organization=organization, pk__in=[key for key in keys if key]
        ).values_list("pk", "full_name")
    )


def _dimension_rows(scope, period, dimension):
    tz = pytz.timezone(scope.organization.timezone)
    marks = _in_period(_scoped_marks(scope), "lesson__starts_at", period, scope.organization)
    lessons = _held_lessons(scope, period)

    if dimension == "branch":
        marks = marks.annotate(
            dimension_key=Coalesce("lesson__group__branch_id", "lesson__room__branch_id")
        )
        lessons = lessons.annotate(dimension_key=Coalesce("group__branch_id", "room__branch_id"))
        label_model = Branch
    elif dimension == "direction":
        marks = marks.annotate(dimension_key=F("lesson__group__direction_id"))
        lessons = lessons.annotate(dimension_key=F("group__direction_id"))
        label_model = Direction
    elif dimension == "group":
        marks = marks.annotate(dimension_key=F("lesson__group_id"))
        lessons = lessons.annotate(dimension_key=F("group_id"))
        label_model = Group
    elif dimension == "teacher":
        marks = marks.annotate(dimension_key=F("lesson__teacher_id"))
        lessons = lessons.annotate(dimension_key=F("teacher_id"))
        label_model = User
    elif dimension == "weekday":
        marks = marks.annotate(dimension_key=ExtractIsoWeekDay("lesson__starts_at", tzinfo=tz))
        lessons = lessons.annotate(dimension_key=ExtractIsoWeekDay("starts_at", tzinfo=tz))
        label_model = None
    else:
        raise ValueError(f"Неизвестный разрез посещаемости: {dimension}")

    mark_rows = {
        row["dimension_key"]: row
        for row in marks.values("dimension_key")
        .annotate(
            marked=Count("id"),
            attended=Count("id", filter=Q(status__in=VISITED)),
            absences=Count("id", filter=Q(status=Attendance.Status.ABSENT)),
        )
        .order_by()
    }
    lesson_rows = dict(
        lessons.values("dimension_key")
        .annotate(value=Count("id"))
        .values_list("dimension_key", "value")
    )
    keys = set(mark_rows) | set(lesson_rows)
    if dimension == "weekday":
        labels = {key: WEEKDAYS[key - 1] for key in keys if key}
    elif label_model is User:
        labels = _staff_labels(scope.organization, keys)
    else:
        labels = _labels(label_model, scope.organization, keys)
    rows = []
    for key in keys:
        counts = mark_rows.get(key, {})
        marked = counts.get("marked", 0)
        attended = counts.get("attended", 0)
        rows.append(
            {
                "key": str(key) if key is not None else None,
                "label": labels.get(key) if key is not None else None,
                "lessons_held": lesson_rows.get(key, 0),
                "marked": marked,
                "attended": attended,
                "absences": counts.get("absences", 0),
                "value": _percent(attended, marked),
            }
        )
    rows.sort(
        key=lambda row: (
            row["value"] is None,
            row["value"] if row["value"] is not None else 101,
            row["label"] or "",
        )
    )
    return rows


def _weekly(scope, period):
    tz = pytz.timezone(scope.organization.timezone)
    marks = _in_period(_scoped_marks(scope), "lesson__starts_at", period, scope.organization)
    lessons = _held_lessons(scope, period)
    mark_rows = {
        row["week"].date(): row
        for row in marks.annotate(week=TruncWeek("lesson__starts_at", tzinfo=tz))
        .values("week")
        .annotate(
            marked=Count("id"),
            attended=Count("id", filter=Q(status__in=VISITED)),
            absences=Count("id", filter=Q(status=Attendance.Status.ABSENT)),
        )
        .order_by()
    }
    lesson_rows = dict(
        lessons.annotate(week=TruncWeek("starts_at", tzinfo=tz))
        .values("week")
        .annotate(value=Count("id"))
        .values_list("week", "value")
    )
    lesson_rows = {week.date(): value for week, value in lesson_rows.items()}

    week = period.start - timedelta(days=period.start.weekday())
    rows = []
    while week <= period.end:
        counts = mark_rows.get(week, {})
        marked = counts.get("marked", 0)
        attended = counts.get("attended", 0)
        rows.append(
            {
                "date": week.isoformat(),
                "lessons_held": lesson_rows.get(week, 0),
                "marked": marked,
                "attended": attended,
                "absences": counts.get("absences", 0),
                "value": _percent(attended, marked),
            }
        )
        week += timedelta(days=7)
    return rows


def _absence_reasons(marks):
    labels = dict(Attendance.AbsenceReason.choices)
    return [
        {
            "key": row["absence_reason"] or None,
            "label": labels.get(row["absence_reason"]) if row["absence_reason"] else None,
            "value": row["value"],
        }
        for row in marks.filter(status=Attendance.Status.ABSENT)
        .values("absence_reason")
        .annotate(value=Count("id"))
        .order_by("-value", "absence_reason")
    ]


def _child_counts(queryset):
    return {
        row["child_id"]: row
        for row in queryset.values("child_id", "child__full_name")
        .annotate(
            marked=Count("id"),
            attended=Count("id", filter=Q(status__in=VISITED)),
            absences=Count("id", filter=Q(status=Attendance.Status.ABSENT)),
        )
        .order_by()
    }


def child_attendance_deviation(scope, period):
    """База для TRU-122: текущая доля пропусков минус личная норма.

    Норма считается по 8 неделям перед выбранным периодом. Запись с
    недостаточной историей остаётся в ответе, но has_baseline=False —
    риск-лист не должен делать из неё автоматический вывод.
    """

    current = _in_period(_scoped_marks(scope), "lesson__starts_at", period, scope.organization)
    baseline_period = Period(
        period.start - timedelta(days=BASELINE_DAYS),
        period.start - timedelta(days=1),
    )
    baseline = _in_period(
        _scoped_marks(scope), "lesson__starts_at", baseline_period, scope.organization
    )
    current_rows = _child_counts(current)
    baseline_rows = _child_counts(baseline)
    rows = []
    for child_id, now in current_rows.items():
        before = baseline_rows.get(child_id, {})
        current_absence_rate = _percent(now["absences"], now["marked"])
        baseline_marks = before.get("marked", 0)
        baseline_absence_rate = _percent(before.get("absences", 0), baseline_marks)
        has_baseline = baseline_marks >= MIN_BASELINE_MARKS
        change = (
            round(current_absence_rate - baseline_absence_rate, 1)
            if has_baseline
            and current_absence_rate is not None
            and baseline_absence_rate is not None
            else None
        )
        trend = "unknown"
        if change is not None:
            trend = "rising" if change >= 10 else "falling" if change <= -10 else "stable"
        rows.append(
            {
                "id": str(child_id),
                "name": now["child__full_name"],
                "marked": now["marked"],
                "attended": now["attended"],
                "absences": now["absences"],
                "attendance_rate": _percent(now["attended"], now["marked"]),
                "absence_rate": current_absence_rate,
                "baseline": {
                    "from": baseline_period.start.isoformat(),
                    "to": baseline_period.end.isoformat(),
                    "marked": baseline_marks,
                    "absences": before.get("absences", 0),
                    "absence_rate": baseline_absence_rate,
                },
                "has_baseline": has_baseline,
                "absence_change_pp": change,
                "trend": trend,
            }
        )
    rows.sort(
        key=lambda row: (
            not row["has_baseline"],
            -(row["absence_change_pp"] if row["absence_change_pp"] is not None else -1000),
            -row["absences"],
            row["name"],
        )
    )
    return rows


def attendance_trends(scope, period):
    marks = _in_period(_scoped_marks(scope), "lesson__starts_at", period, scope.organization)
    totals = _totals(marks)
    return {
        "period": period.as_dict(),
        "summary": {
            "lessons_held": _held_lessons(scope, period).count(),
            **totals,
            "attendance_rate": _percent(totals["attended"], totals["marked"]),
        },
        "weekly": _weekly(scope, period),
        "absence_reasons": _absence_reasons(marks),
        "breakdowns": {
            dimension: _dimension_rows(scope, period, dimension)
            for dimension in ("group", "direction", "branch", "teacher", "weekday")
        },
        "children": child_attendance_deviation(scope, period),
        "baseline": {
            "days": BASELINE_DAYS,
            "minimum_marks": MIN_BASELINE_MARKS,
        },
    }
