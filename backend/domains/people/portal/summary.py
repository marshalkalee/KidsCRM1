"""
Главный экран кабинета (TRU-138): три вопроса родителя — когда следующее
занятие, сколько занятий осталось, сколько к оплате.

Цифры не считаются заново: остаток и статус — из абонемента (тот же
sessions_remaining_cache, что в карточке ребёнка), долг — debt_by_child
(TRU-73, тот же, что у администратора), «заканчивается» — is_ending_soon
(тот же порог, что в «Продлениях»). Если родитель и администратор увидят
разные цифры — это скандал, а не баг.
"""

from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from domains.money.subscriptions.debt import debt_by_child
from domains.money.subscriptions.models import Subscription
from domains.money.subscriptions.renewals import is_ending_soon
from domains.platform.core.utils import today_for_org
from domains.platform.tenants.org_settings import KASPI_PAYMENT_DETAILS, get_org_setting
from domains.scheduling.schedule.models import Lesson


def upcoming_lessons(child, limit=3):
    """Ближайшие занятия ребёнка — по тому же правилу, что
    Lesson.participants (наоборот): занятия его групп, индивидуальные и
    записи поверх группы (отработки, пробные). Отменённые и перенесённые
    не показываем — у перенесённого есть новое занятие."""
    lessons = (
        Lesson.objects.filter(
            organization_id=child.organization_id,
            starts_at__gte=timezone.now(),
            status=Lesson.Status.SCHEDULED,
        )
        .filter(
            Q(group__memberships__child=child, group__memberships__left_at__isnull=True)
            | Q(individual_children=child)
            | Q(enrollments__child=child, enrollments__cancelled_at__isnull=True)
        )
        .select_related("group__direction", "group__branch", "room__branch", "teacher")
        .distinct()
        .order_by("starts_at")[:limit]
    )
    return [lesson_row(lesson, child) for lesson in lessons]


def _local(dt, tz):
    return dt.astimezone(tz).isoformat()


def lesson_row(lesson, child):
    """Время — в часовом поясе центра (с отметкой смещения): родитель видит
    то же время, что на расписании центра, где бы ни был его телефон."""
    tz = timezone.zoneinfo.ZoneInfo(child.organization.timezone or "Asia/Almaty")
    group = lesson.group
    branch = (group.branch if group else None) or (lesson.room.branch if lesson.room_id else None)
    kind = "group"
    if not group:
        kind = "individual"
    elif not group.memberships.filter(child=child, left_at__isnull=True).exists():
        enrollment = lesson.enrollments.filter(child=child, cancelled_at__isnull=True).first()
        kind = enrollment.kind if enrollment else "group"
    return {
        "id": str(lesson.id),
        "starts_at": _local(lesson.starts_at, tz),
        "ends_at": _local(lesson.ends_at, tz),
        "group": group.name if group else "",
        "direction": group.direction.name if group and group.direction_id else "",
        "branch": branch.name if branch else "",
        "address": branch.address if branch else "",
        "room": lesson.room.name if lesson.room_id else "",
        "teacher": lesson.teacher.full_name if lesson.teacher_id else "",
        "kind": kind,
    }


def current_subscription(child):
    """Действующий (или замороженный) абонемент, иначе — последний."""
    subscriptions = Subscription.objects.filter(
        child=child, deleted_at__isnull=True
    ).select_related("subscription_type_version", "organization")
    current = (
        subscriptions.filter(status__in=[Subscription.Status.ACTIVE, Subscription.Status.FROZEN])
        .order_by("-starts_on")
        .first()
    )
    return current or subscriptions.order_by("-starts_on").first()


def subscription_row(subscription):
    if subscription is None:
        return None
    freeze = None
    if subscription.status == Subscription.Status.FROZEN:
        active = subscription.freezes.filter(deleted_at__isnull=True).order_by("-starts_on").first()
        freeze = active and {"starts_on": active.starts_on, "ends_on": active.ends_on}
    version = subscription.subscription_type_version
    return {
        "id": str(subscription.id),
        "name": version.name,
        "status": subscription.status,
        "starts_on": subscription.starts_on,
        "ends_on": subscription.ends_on,
        "is_unlimited": version.is_unlimited,
        "sessions_total": None if version.is_unlimited else version.quota_sessions,
        "sessions_remaining": subscription.sessions_remaining_cache,
        "ending_soon": is_ending_soon(subscription),
        "freeze": freeze,
    }


def summary(child):
    organization = child.organization
    debt = debt_by_child(organization, [child.id]).get(child.id, Decimal(0))
    return {
        "today": today_for_org(organization),
        "next_lessons": upcoming_lessons(child),
        "subscription": subscription_row(current_subscription(child)),
        "to_pay": str(debt),
        "payment": {"kaspi": get_org_setting(organization, KASPI_PAYMENT_DETAILS)},
    }
