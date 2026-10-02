"""Точки создания системных задач из других доменов."""

import datetime

from django.utils import timezone

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
) -> Task:
    """TaskService.create — единый вход для создания задач из любого домена
    (ТЗ п. 3.1, контракт §9 в docs/contracts.md). organization берётся у
    assignee, если не передана явно — исполнитель всегда в своей
    организации, дублировать её на каждый вызов необязательно."""
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
    )


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
    принцип, что у visible_leads в platform.leads)."""
    qs = Task.objects.for_tenant(user.organization)
    if user.role == User.Role.OWNER:
        return qs
    branch_ids = list(user.branches.values_list("id", flat=True))
    if not branch_ids:
        return qs
    from django.db.models import Q

    return qs.filter(Q(branch_id__in=branch_ids) | Q(branch__isnull=True) | Q(assigned_to=user))
