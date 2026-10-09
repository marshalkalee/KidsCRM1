"""Точки создания системных задач из других доменов."""

import datetime

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from domains.platform.core.utils import today_for_org
from domains.platform.tenants.org_settings import (
    RULE_MISSING_SUBSCRIPTION_ENABLED,
    RULE_TRIAL_NO_SHOW_ENABLED,
    get_org_setting,
)
from domains.platform.users.models import User

from .models import Task


def create_admin_task_for_missing_subscription(*, attendance):
    """attendance — domains.scheduling.attendance.models.Attendance с уже
    выставленным no_subscription_flag=True (ТЗ п. 5.2, TRU-108)."""
    organization = attendance.lesson.organization
    if not get_org_setting(organization, RULE_MISSING_SUBSCRIPTION_ENABLED):
        return None
    return create_task(
        type=Task.Type.MISSING_SUBSCRIPTION,
        assignee=None,
        due_date=None,
        subject=f"Оформить абонемент: {attendance.child.full_name}",
        organization=organization,
        source=Task.Source.AUTO,
        branch=attendance.lesson.room.branch if attendance.lesson.room_id else None,
        child=attendance.child,
        source_key=f"missing_subscription:{attendance.id}",
    )


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
    if not get_org_setting(lead.organization, RULE_TRIAL_NO_SHOW_ENABLED):
        return None
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
            "child": child,
            "source": Task.Source.AUTO,
            "due_at": timezone.now() + datetime.timedelta(days=1),
            "title": f"Удержать клиента: {child.full_name}",
            "description": "Сигналы риска: " + ", ".join(labels[key] for key in signals),
        },
    )
    return task, created


def create_task(
    *,
    type,
    assignee,
    due_date,
    subject,
    organization=None,
    source=Task.Source.MANUAL,
    branch=None,
    lead=None,
    child=None,
    created_by=None,
    description="",
    source_key="",
):
    """TaskService.create — единый вход для создания задач из любого домена
    (ТЗ п. 3.1, контракт §9 в docs/contracts.md). organization берётся у
    assignee, если не передана явно. Возвращает None, если задача с таким
    же (organization, type, source_key) уже открыта — идемпотентность
    автоправил (TRU-108): для ручного создания source_key всегда пустой,
    ограничение на него не распространяется, поведение не меняется."""
    try:
        with transaction.atomic():
            return Task.objects.create(
                organization=organization or assignee.organization,
                type=type,
                assigned_to=assignee,
                due_at=due_date,
                title=subject,
                description=description,
                source=source,
                branch=branch,
                lead=lead,
                child=child,
                created_by=created_by,
                source_key=source_key,
            )
    except IntegrityError:
        return None


def complete_task(task: Task, *, actor, comment="") -> Task:
    task.status = Task.Status.DONE
    task.closing_comment = comment
    task.save(update_fields=["status", "closing_comment", "updated_at"])
    return task


def cancel_task(task: Task, *, actor, comment="") -> Task:
    task.status = Task.Status.CANCELLED
    task.closing_comment = comment
    task.save(update_fields=["status", "closing_comment", "updated_at"])
    return task


def visible_tasks(user):
    """Кто видит задачу (ТЗ п. 2): владелец — все, управляющий/админ с
    закреплёнными филиалами — задачи своих филиалов, задачи без филиала
    и назначенные лично на него; без закреплённых филиалов — все (тот же
    принцип, что у visible_leads в platform.leads). Преподаватель — только
    свои."""
    qs = Task.objects.for_tenant(user.organization)
    if user.role == User.Role.OWNER:
        return qs
    # Преподаватель — только поручения ему лично (костюмы, фото с концерта).
    if user.role == User.Role.TEACHER:
        return qs.filter(assigned_to=user)
    branch_ids = list(user.branches.values_list("id", flat=True))
    if not branch_ids:
        return qs
    return qs.filter(Q(branch_id__in=branch_ids) | Q(branch__isnull=True) | Q(assigned_to=user))
