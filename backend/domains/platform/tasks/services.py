"""Точки создания системных задач из других доменов."""

import datetime

from django.utils import timezone

from domains.platform.core.utils import today_for_org
from domains.platform.users.models import User

from .models import Task


def create_admin_task_for_missing_subscription(*, attendance):
    """attendance — domains.scheduling.attendance.models.Attendance с уже
    выставленным no_subscription_flag=True. Ничего не делает в M1."""
    return None


def _lead_assignee(lead):
    if lead.assigned_to_id and lead.assigned_to and lead.assigned_to.is_active:
        return lead.assigned_to
    return (
        User.objects.filter(
            organization=lead.organization,
            is_active=True,
            role__in=[User.Role.ADMIN, User.Role.MANAGER, User.Role.OWNER],
        )
        .order_by("role", "full_name")
        .first()
    )


def create_trial_no_show_task(*, lead, lesson, attendance):
    """Создать один звонок по конкретной неявке на пробное.

    Повторная отметка ``absent`` возвращает существующую задачу. Для новой
    записи на другое пробное создастся новая задача, потому что у неё будет
    другой Attendance и, соответственно, другой ``source_key``.
    """
    local_start = timezone.localtime(lesson.starts_at)
    lesson_name = lesson.group.name if lesson.group_id else "Индивидуальное занятие"
    assignee = _lead_assignee(lead)
    task, _created = Task.objects.get_or_create(
        organization=lead.organization,
        type=Task.Type.TRIAL_NO_SHOW,
        source_key=f"attendance:{attendance.id}",
        defaults={
            "lead": lead,
            "assigned_to": assignee,
            "due_at": timezone.now() + datetime.timedelta(hours=1),
            "title": "Перезвонить: не пришёл на пробное",
            "description": (
                f"{lead.child_name or lead.parent_name} не пришёл на пробное занятие "
                f"«{lesson_name}» {local_start:%d.%m.%Y в %H:%M}. "
                "Свяжитесь с родителем. Если заявка закрывается отказом, "
                "выберите причину «Не пришёл на пробное»."
            ),
        },
    )
    return task


def cancel_trial_no_show_task(*, attendance) -> int:
    """Закрыть ошибочную неявку после исправления/сброса отметки."""
    return (
        Task.objects.for_tenant(attendance.organization)
        .filter(
            type=Task.Type.TRIAL_NO_SHOW,
            source_key=f"attendance:{attendance.id}",
            status=Task.Status.OPEN,
        )
        .update(status=Task.Status.CANCELLED, updated_at=timezone.now())
    )


def create_retention_task(*, child, actor, signals):
    """Создать одну открытую задачу удержания на ребёнка."""
    assignee = actor if actor and actor.is_active else None
    if assignee is None:
        assignee = (
            User.objects.filter(
                organization=child.organization,
                is_active=True,
                role__in=[User.Role.ADMIN, User.Role.MANAGER, User.Role.OWNER],
            )
            .order_by("role", "full_name")
            .first()
        )
    labels = {
        "attendance": "участились пропуски",
        "subscription": "заканчивается или истёк абонемент",
        "debt": "есть задолженность",
    }
    task, created = Task.objects.get_or_create(
        organization=child.organization,
        type=Task.Type.RETENTION,
        source_key=f"retention:{child.id}:{today_for_org(child.organization):%Y-%m}",
        defaults={
            "assigned_to": assignee,
            "due_at": timezone.now() + datetime.timedelta(days=1),
            "title": f"Удержать клиента: {child.full_name}",
            "description": "Сигналы риска: " + ", ".join(labels[key] for key in signals),
        },
    )
    return task, created
