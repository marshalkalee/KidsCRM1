"""Лента карточки задачи (TRU-184): комментарии и события из журнала
изменений (AuditLog) одной лентой по времени, старые сверху.

Каждое событие — готовая строка по-русски: экран её только показывает.
Имена в строках — в именительном падеже («Задача передана: Анель →
Дарья»): склонять имена мы не умеем, а пола сотрудника в профиле нет.

Создание и закрытие берутся из самой задачи, а не только из журнала:
автоправила и закрытие запроса родителя пишут задачу мимо API и журнала,
у старых задач журнала закрытия нет — без этого лента была бы пустой.
"""

import datetime

import pytz
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from domains.platform.core.audit import AuditLog

from .models import Task, TaskComment

# Сколько минут автор может править и удалять свой комментарий.
EDIT_WINDOW = datetime.timedelta(minutes=15)

# Какое автоправило создало задачу — по началу source_key (services.py,
# leads/rules.py, subscriptions/debt.py, subscriptions/statuses.py,
# portal/lesson_requests.py). Новое правило без строки здесь покажется
# названием типа задачи.
RULE_LABELS = {
    "missing_subscription": "занятие без абонемента",
    "attendance": "не пришёл на пробное",
    "retention": "риск ухода",
    "renewal_offer": "абонемент заканчивается",
    "debt_reminder": "просроченный долг",
    "lead_stale": "заявка без движения",
    "parent-request": "запрос из кабинета родителя",
}

STATUS_TEXT = {
    Task.Status.DONE: "Выполнена",
    Task.Status.CANCELLED: "Отменена",
    Task.Status.OPEN: "Снова открыта",
}


def is_automatic(task):
    """Автоправило: source=auto, или системный ключ без автора (неявка на
    пробное создаётся с source=manual, но человек её не ставил)."""
    return task.source == Task.Source.AUTO or bool(task.source_key and not task.created_by_id)


def rule_label(task):
    prefix = task.source_key.split(":", 1)[0] if task.source_key else ""
    return RULE_LABELS.get(prefix) or task.get_type_display()


def can_edit_comment(comment, user, now=None):
    now = now or timezone.now()
    return comment.author_id == user.id and now - comment.created_at <= EDIT_WINDOW


def _tz(task):
    return pytz.timezone(task.organization.timezone or "Asia/Almaty")


def due_text(value, tz):
    """«14.10» — срок до конца дня (так ставит экран), иначе «14.10 в 15:20»."""
    if not value:
        return None
    if isinstance(value, str):
        value = datetime.datetime.fromisoformat(value)
    local = value.astimezone(tz)
    if (local.hour, local.minute) == (23, 59):
        return f"{local:%d.%m}"
    return f"{local:%d.%m в %H:%M}"


def _event(at, author, text, kind="event", comment=None):
    return {
        "kind": kind,
        "at": at,
        "author": str(author.id) if author else None,
        "author_name": author.full_name if author else None,
        "text": text,
        "comment": comment,
    }


def _first_assignee(task, entries):
    """Кому поручили при создании: задача уже могла быть передана, и
    текущий исполнитель — не первый."""
    for entry in entries:
        if entry.action == AuditLog.Action.CREATE and entry.after:
            return entry.after.get("assigned_to")
        if "assigned_to" in (entry.before or {}):
            return entry.before["assigned_to"]
    return task.assigned_to.full_name if task.assigned_to else None


def _created(task, entries):
    if is_automatic(task):
        return _event(task.created_at, None, f"Создана автоматически: {rule_label(task)}")
    text = "Задача создана"
    assignee = _first_assignee(task, entries)
    creator = task.created_by.full_name if task.created_by else None
    if assignee and assignee != creator:
        text += f", исполнитель: {assignee}"
    return _event(task.created_at, task.created_by, text)


def _audit_lines(entry, tz):
    """Строки одной записи журнала. Создание здесь не показываем — оно уже
    есть из самой задачи."""
    before = entry.before or {}
    after = entry.after or {}
    lines = []
    if entry.action == AuditLog.Action.CREATE:
        return lines
    if "assigned_to" in after:
        old, new = before.get("assigned_to"), after.get("assigned_to")
        if old and new:
            lines.append(f"Задача передана: {old} → {new}")
        elif new:
            lines.append(f"Задача поручена: {new}")
        else:
            lines.append(f"Исполнитель снят (был: {old})" if old else "Исполнитель снят")
    if "due_at" in after:
        new = due_text(after.get("due_at"), tz)
        lines.append(f"Срок перенесён на {new}" if new else "Срок снят")
    if "status" in after:
        text = STATUS_TEXT.get(after["status"], "Статус изменён")
        comment = (after.get("closing_comment") or "").strip()
        lines.append(f"{text}: «{comment}»" if comment else text)
    return lines


def build_timeline(task, user):
    """Лента для пользователя user (флаг can_edit у его свежих комментариев)."""
    tz = _tz(task)
    now = timezone.now()
    entries = list(
        AuditLog.objects.filter(
            organization_id=task.organization_id,
            content_type=ContentType.objects.get_for_model(Task),
            object_id=task.pk,
        )
        .select_related("actor")
        .order_by("created_at")
    )
    items = [_created(task, entries)]
    closed_in_log = False
    for entry in entries:
        for text in _audit_lines(entry, tz):
            items.append(_event(entry.created_at, entry.actor, text))
        if "status" in (entry.after or {}):
            closed_in_log = True

    # Закрыта мимо журнала (запрос родителя, старые задачи) — строка из
    # самой задачи, время — последнее изменение.
    if task.status != Task.Status.OPEN and not closed_in_log:
        text = STATUS_TEXT[task.status]
        if task.closing_comment:
            text += f": «{task.closing_comment}»"
        items.append(_event(task.updated_at, None, text))

    comments = (
        TaskComment.objects.for_tenant(task.organization).filter(task=task).select_related("author")
    )
    for comment in comments:
        items.append(
            _event(
                comment.created_at,
                comment.author,
                comment.text,
                kind="comment",
                comment={
                    "id": str(comment.id),
                    "edited": comment.edited_at is not None,
                    "can_edit": can_edit_comment(comment, user, now),
                },
            )
        )

    items.sort(key=lambda item: item["at"])
    for item in items:
        item["at"] = item["at"].isoformat()
    return items
