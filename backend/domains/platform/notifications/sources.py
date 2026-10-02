"""
Источники уведомлений (TRU-72). Каждый — функция (user, branch_ids) →
Item: сколько, когда появилось последнее, куда вести. Считают теми же
функциями, что и экраны, куда ведёт уведомление: иначе счётчик в шапке
разойдётся со списком (критерий приёмки).

branch_ids — филиалы, которые видит сотрудник (None — все): владелец —
все или выбранный в шапке; остальные — закреплённые за ними.
"""

import datetime
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from domains.money.subscriptions.debt import debtor_subscriptions
from domains.people.clients.child_list import (
    children_without_subscription,
    overdue_debt_threshold,
)
from domains.platform.core.role_permissions import can_manage_leads, can_view_client_money
from domains.platform.leads.models import Lead
from domains.platform.leads.services import visible_leads
from domains.platform.users.models import User


@dataclass
class Item:
    kind: str
    count: int = 0
    latest_at: datetime.datetime | None = None
    link: str = ""
    available: bool = True
    extra: dict = field(default_factory=dict)


def new_leads(user, branch_ids):
    """Новые заявки — ещё никто не связался (TRU-99)."""
    if not can_manage_leads(user):
        return None
    qs = visible_leads(user).filter(kind=Lead.Kind.NEW, status=Lead.Status.NEW)
    if branch_ids is not None:
        qs = qs.filter(Q(branch_id__in=branch_ids) | Q(branch__isnull=True))
    latest = qs.order_by("-created_at").values_list("created_at", flat=True).first()
    return Item("new_leads", qs.count(), latest, "/leads")


def overdue_tasks(user, branch_ids):
    """Просроченные открытые задачи (ТЗ п. 5.2, TRU-109) — эскалация
    управляющему. Админ видит свои и своего филиала (TRU-107), управляющий
    и владелец — для перехода на экран эскалации."""
    if user.role not in (User.Role.OWNER, User.Role.MANAGER, User.Role.ADMIN):
        return None
    from domains.platform.tasks.models import Task
    from domains.platform.tasks.services import visible_tasks

    qs = visible_tasks(user).filter(status=Task.Status.OPEN, due_at__lt=timezone.now())
    if branch_ids is not None:
        qs = qs.filter(Q(branch_id__in=branch_ids) | Q(branch__isnull=True))
    latest = qs.order_by("-due_at").values_list("due_at", flat=True).first()
    link = "/tasks/escalation" if user.role in (User.Role.OWNER, User.Role.MANAGER) else "/tasks"
    return Item("overdue_tasks", qs.count(), latest, link)


def unmarked_lessons(user, branch_ids):
    """
    Вчерашние занятия с неполной отметкой посещаемости — то же определение,
    что у AttendanceViewSet.unmarked_yesterday (Дарья, TRU-52): не отменённые
    и не перенесённые, отмечено меньше участников, чем есть. Преподаватель
    видит только свои.
    """
    if user.role == User.Role.ACCOUNTANT:
        return None
    from domains.scheduling.attendance.models import Attendance
    from domains.scheduling.schedule.models import Lesson

    organization = user.organization
    tz = timezone.zoneinfo.ZoneInfo(organization.timezone or "Asia/Almaty")
    today = timezone.now().astimezone(tz).date()
    yesterday = today - datetime.timedelta(days=1)
    lessons = (
        Lesson.objects.for_tenant(organization)
        .exclude(status__in=[Lesson.Status.CANCELLED, Lesson.Status.RESCHEDULED])
        .filter(starts_at__date=yesterday)
    )
    if user.role == User.Role.TEACHER:
        lessons = lessons.filter(teacher=user)
    if branch_ids is not None:
        lessons = lessons.filter(
            Q(room__branch_id__in=branch_ids) | Q(group__branch_id__in=branch_ids)
        )
    unmarked = []
    for lesson in lessons:
        participants = list(lesson.participants())
        if not participants:
            continue
        marked = (
            Attendance.objects.for_tenant(organization)
            .filter(lesson=lesson, child__in=participants)
            .count()
        )
        if marked < len(participants):
            unmarked.append(lesson.id)
    # Одно занятие — сразу в него, несколько — на экран посещаемости.
    link = f"/attendance?lesson={unmarked[0]}" if len(unmarked) == 1 else "/attendance"
    # «Появились» в полночь по времени центра — каждый день это новое уведомление.
    appeared = datetime.datetime.combine(today, datetime.time.min, tzinfo=tz) if unmarked else None
    return Item(
        "unmarked_lessons", len(unmarked), appeared, link, extra={"date": yesterday.isoformat()}
    )


def no_subscription(user, branch_ids):
    """Занимаются в группе, а действующего абонемента нет (ТЗ п. 4.5)."""
    if not can_view_client_money(user):
        return None
    qs = children_without_subscription(user.organization)
    if branch_ids is not None:
        qs = qs.filter(
            group_memberships__left_at__isnull=True,
            group_memberships__group__branch_id__in=branch_ids,
        ).distinct()
    return Item("no_subscription", qs.count(), None, "/children?no_subscription=1")


def overdue_debts(user, branch_ids):
    """Долг старше порога из настроек организации (ТЗ п. 4.4, 4.5) — та же
    формула, что у списка детей и экрана «Задолженности»."""
    if not can_view_client_money(user):
        return None
    days = overdue_debt_threshold(user.organization)
    qs = debtor_subscriptions(user.organization, min_age_days=days)
    if branch_ids is not None:
        qs = qs.filter(branch_id__in=branch_ids)
    # Долг — агрегат по оплатам, поверх него Sum() в SQL не посчитать:
    # строк немного (только должники), суммируем здесь.
    rows = list(qs.values_list("child_id", "debt"))
    children = len({child_id for child_id, _ in rows})
    total = sum((debt for _, debt in rows), Decimal(0))
    return Item(
        "overdue_debts",
        children,
        None,
        "/children?has_debt=1&debt_overdue=1",
        extra={"total": str(total), "days": days},
    )


SOURCES = [new_leads, unmarked_lessons, overdue_debts, no_subscription, overdue_tasks]
