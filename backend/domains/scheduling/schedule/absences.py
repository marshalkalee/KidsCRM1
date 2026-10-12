"""
Отсутствия сотрудников и занятия «нужна замена» (TRU-182).

Занятие нужно закрыть заменой, если оно запланировано, у него есть
преподаватель и в день занятия (по часам центра) у этого преподавателя
отмечено отсутствие. Считается одним запросом отсутствий на всё окно
занятий — без запроса на каждое занятие.
"""

import datetime

from django.db.models import Q
from django.utils import timezone

from .models import Lesson, StaffAbsence


def _org_tz(organization):
    return timezone.zoneinfo.ZoneInfo(organization.timezone or "Asia/Almaty")


def day_range(organization, first_day, last_day):
    """Границы [first_day 00:00, last_day+1 00:00) в часах центра."""
    tz = _org_tz(organization)
    start = datetime.datetime.combine(first_day, datetime.time.min, tzinfo=tz)
    day_after = last_day + datetime.timedelta(days=1)
    end = datetime.datetime.combine(day_after, datetime.time.min, tzinfo=tz)
    return start, end


def absence_map(organization, lessons):
    """{lesson.id: StaffAbsence} для запланированных занятий, чей преподаватель
    в этот день отсутствует."""
    lessons = [
        lesson
        for lesson in lessons
        if lesson.teacher_id and lesson.status == Lesson.Status.SCHEDULED
    ]
    if not lessons:
        return {}
    tz = _org_tz(organization)
    days = {lesson.id: lesson.starts_at.astimezone(tz).date() for lesson in lessons}
    absences = StaffAbsence.objects.for_tenant(organization).filter(
        staff_id__in={lesson.teacher_id for lesson in lessons},
        starts_on__lte=max(days.values()),
        ends_on__gte=min(days.values()),
    )
    by_staff = {}
    for absence in absences:
        by_staff.setdefault(absence.staff_id, []).append(absence)
    result = {}
    for lesson in lessons:
        day = days[lesson.id]
        for absence in by_staff.get(lesson.teacher_id, ()):
            if absence.starts_on <= day <= absence.ends_on:
                result[lesson.id] = absence
                break
    return result


def lessons_of(organization, staff_id, first_day, last_day, scope=None):
    """Запланированные занятия сотрудника за дни [first_day, last_day]."""
    start, end = day_range(organization, first_day, last_day)
    qs = Lesson.objects.for_tenant(organization).filter(
        teacher_id=staff_id,
        status=Lesson.Status.SCHEDULED,
        starts_at__gte=start,
        starts_at__lt=end,
    )
    if scope is not None:
        qs = qs.filter(Q(group__branch_id__in=scope) | Q(room__branch_id__in=scope))
    return qs


def uncovered_lessons(organization, first_day, last_day, scope=None):
    """Занятия без преподавателя за период: [(lesson, absence)] по времени."""
    absences = StaffAbsence.objects.for_tenant(organization).filter(
        starts_on__lte=last_day, ends_on__gte=first_day
    )
    staff_ids = set(absences.values_list("staff_id", flat=True))
    if not staff_ids:
        return []
    start, end = day_range(organization, first_day, last_day)
    qs = (
        Lesson.objects.for_tenant(organization)
        .filter(
            teacher_id__in=staff_ids,
            status=Lesson.Status.SCHEDULED,
            starts_at__gte=start,
            starts_at__lt=end,
        )
        .select_related("teacher", "room__branch", "group__branch", "group__direction")
        .order_by("starts_at")
    )
    if scope is not None:
        qs = qs.filter(Q(group__branch_id__in=scope) | Q(room__branch_id__in=scope))
    lessons = list(qs)
    found = absence_map(organization, lessons)
    return [(lesson, found[lesson.id]) for lesson in lessons if lesson.id in found]
