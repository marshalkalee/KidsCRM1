"""Автоправило: прошедшее занятие, где кто-то из детей не отмечен, → задача
«Отметить посещаемость» преподавателю этого занятия (нет преподавателя —
администратору филиала). Решение «был / не был» принимает человек:
неотмеченное занятие само не сгорает и не списывается. Задача закрывается
сама, когда отмечены все; не отметили до конца дня — она попадает в
«Просроченные у команды». Колокольчик «не отмечено» показывает только
вчера — задача не даёт забытому занятию пропасть из виду.

Идемпотентность — через Task.source_key (уникален, пока задача открыта)."""

import datetime

from django.utils import timezone

from domains.platform.core.utils import day_bounds_for_org, today_for_org
from domains.platform.tasks.models import RuleRun, Task
from domains.platform.tasks.services import branch_assignee, complete_task, create_task
from domains.platform.tenants.models import Organization
from domains.platform.tenants.org_settings import (
    RULE_UNMARKED_ATTENDANCE_ENABLED,
    get_org_setting,
)
from domains.scheduling.schedule.models import Lesson

from .models import Attendance

# Сколько дней назад искать: пропущенный ночной запуск или отметку,
# снятую позже, правило подберёт в следующий раз.
LOOKBACK_DAYS = 7
_INACTIVE = (Lesson.Status.CANCELLED, Lesson.Status.RESCHEDULED)


def _source_key(lesson):
    return f"unmarked_attendance:{lesson.id}"


def _lesson_branch(lesson):
    return lesson.group.branch if lesson.group_id else getattr(lesson.room, "branch", None)


def unmarked_children(lesson):
    marked = Attendance.objects.filter(lesson=lesson).values_list("child_id", flat=True)
    return list(lesson.participants().exclude(id__in=marked).order_by("full_name"))


def _task_text(lesson, missing):
    tz = timezone.zoneinfo.ZoneInfo(lesson.organization.timezone or "Asia/Almaty")
    start = timezone.localtime(lesson.starts_at, tz)
    what = lesson.group.name if lesson.group_id else "Индивидуальное занятие"
    title = f"Отметить посещаемость: {what}, {start:%d.%m} в {start:%H:%M}"
    description = "Не отмечены: " + ", ".join(child.full_name for child in missing)
    return title, description


def close_task_if_marked(lesson) -> bool:
    """Все отмечены (или занятие отменено) — открытая задача закрывается."""
    task = (
        Task.objects.for_tenant(lesson.organization)
        .filter(
            type=Task.Type.MARK_ATTENDANCE,
            source_key=_source_key(lesson),
            status=Task.Status.OPEN,
        )
        .first()
    )
    if task is None:
        return False
    if lesson.status not in _INACTIVE and unmarked_children(lesson):
        return False
    complete_task(task, actor=None, comment="Посещаемость отмечена")
    return True


def _close_resolved(organization):
    open_tasks = Task.objects.for_tenant(organization).filter(
        type=Task.Type.MARK_ATTENDANCE, status=Task.Status.OPEN, source=Task.Source.AUTO
    )
    for task in open_tasks:
        lesson_id = task.source_key.removeprefix("unmarked_attendance:")
        lesson = Lesson.objects.for_tenant(organization).filter(pk=lesson_id).first()
        if lesson is None:
            complete_task(task, actor=None, comment="Занятие удалено")
        else:
            close_task_if_marked(lesson)


def create_tasks_for_unmarked_lessons() -> int:
    created = 0
    for organization in Organization.objects.all():
        if not get_org_setting(organization, RULE_UNMARKED_ATTENDANCE_ENABLED):
            continue
        _close_resolved(organization)
        today = today_for_org(organization)
        since, _ = day_bounds_for_org(organization, today - datetime.timedelta(days=LOOKBACK_DAYS))
        today_start, today_end = day_bounds_for_org(organization, today)
        lessons = (
            Lesson.objects.for_tenant(organization)
            .exclude(status__in=_INACTIVE)
            .filter(starts_at__gte=since, starts_at__lt=today_start)
            .select_related("group__branch", "room__branch", "teacher")
        )
        created_for_org = 0
        for lesson in lessons:
            missing = unmarked_children(lesson)
            if not missing:
                continue
            branch = _lesson_branch(lesson)
            teacher = lesson.teacher
            own_teacher = (
                teacher is not None
                and teacher.is_active
                and teacher.organization_id == organization.id
            )
            assignee = teacher if own_teacher else branch_assignee(organization, branch)
            if assignee is None:
                continue
            title, description = _task_text(lesson, missing)
            task = create_task(
                type=Task.Type.MARK_ATTENDANCE,
                assignee=assignee,
                due_date=today_end,
                subject=title,
                description=description,
                organization=organization,
                source=Task.Source.AUTO,
                branch=branch,
                source_key=_source_key(lesson),
            )
            if task is not None:
                created_for_org += 1
        if created_for_org:
            RuleRun.objects.create(
                organization=organization, rule="unmarked_attendance", tasks_created=created_for_org
            )
        created += created_for_org
    return created
