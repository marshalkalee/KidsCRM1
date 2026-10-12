"""Автоуведомления родителям по правилам организации (TRU-171).

Расчёты долга и окончания абонемента не повторяются: используются
канонические выборки money.subscriptions. Отправка всегда идёт через
messaging.notify(), поэтому согласия, тихие часы, каналы и дедупликация
остаются едиными для ручных и автоматических сообщений.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.utils import timezone

from domains.money.payments.models import Payment
from domains.money.subscriptions.debt import debtor_subscriptions
from domains.money.subscriptions.renewals import expiring_subscriptions
from domains.people.clients.models import ChildContact
from domains.platform.core.utils import day_bounds_for_org, today_for_org
from domains.platform.tenants.models import Organization
from domains.platform.tenants.org_settings import (
    AUTO_NOTIFY_LESSON_CHANGES_ENABLED,
    AUTO_NOTIFY_LESSON_REMINDER_ENABLED,
    AUTO_NOTIFY_LESSON_REMINDER_HOURS,
    AUTO_NOTIFY_PAYMENT_ENABLED,
    AUTO_NOTIFY_SUBSCRIPTION_ENABLED,
    DEBT_OVERDUE_DAYS_THRESHOLD,
    get_org_setting,
)
from domains.scheduling.schedule.models import Lesson

from ..models import MessageCategory, MessagingConsent
from .service import notify


def _contacts(child, *, payer=None):
    """Только контакты с согласием; плательщик имеет приоритет для долга."""
    links = (
        ChildContact.objects.for_tenant(child.organization)
        .filter(child=child, deleted_at__isnull=True, parent_contact__deleted_at__isnull=True)
        .select_related("parent_contact")
    )
    contacts = [link.parent_contact for link in links]
    if payer and any(contact.id == payer.id for contact in contacts):
        contacts = [payer]
    consented_ids = set(
        MessagingConsent.objects.for_tenant(child.organization)
        .filter(
            parent_id__in=[contact.id for contact in contacts],
            category=MessageCategory.UTILITY,
            status=MessagingConsent.Status.OPTED_IN,
        )
        .values_list("parent_id", flat=True)
    )
    return [contact for contact in contacts if contact.id in consented_ids]


def _money(value: Decimal) -> str:
    return f"{value:,.0f} ₸".replace(",", " ")


def _subscription_left(subscription) -> str:
    days = max((subscription.ends_on - today_for_org(subscription.organization)).days, 0)
    sessions = subscription.sessions_remaining_cache
    if sessions is None:
        return f"{days} дн."
    return f"{sessions} зан. / {days} дн."


def _payer_for(subscription):
    payer_id = (
        Payment.objects.for_tenant(subscription.organization)
        .filter(subscription=subscription, payer__isnull=False, deleted_at__isnull=True)
        .order_by("-paid_at")
        .values_list("payer_id", flat=True)
        .first()
    )
    if not payer_id:
        return None
    link = (
        ChildContact.objects.for_tenant(subscription.organization)
        .filter(
            child=subscription.child,
            parent_contact_id=payer_id,
            deleted_at__isnull=True,
        )
        .select_related("parent_contact")
        .first()
    )
    return link.parent_contact if link else None


def dispatch_daily_for_organization(organization, *, today=None) -> int:
    """Долги, окончание абонемента и напоминания о завтрашних занятиях."""
    today = today or today_for_org(organization)
    queued = 0
    if get_org_setting(organization, AUTO_NOTIFY_PAYMENT_ENABLED):
        age = get_org_setting(organization, DEBT_OVERDUE_DAYS_THRESHOLD)
        for subscription in debtor_subscriptions(organization, min_age_days=age):
            payer = _payer_for(subscription)
            for parent in _contacts(subscription.child, payer=payer):
                notify(
                    parent,
                    "payment_due",
                    {"child": subscription.child.full_name, "amount": _money(subscription.debt)},
                    # Один просроченный абонемент — одно напоминание контакту,
                    # а не новое сообщение каждый день после достижения порога.
                    dedup_key=f"auto:payment:{subscription.id}:{parent.id}",
                )
                queued += 1

    if get_org_setting(organization, AUTO_NOTIFY_SUBSCRIPTION_ENABLED):
        for subscription in expiring_subscriptions(organization, today=today):
            for parent in _contacts(subscription.child):
                notify(
                    parent,
                    "subscription_ending",
                    {
                        "child": subscription.child.full_name,
                        "left": _subscription_left(subscription),
                    },
                    dedup_key=f"auto:subscription:{subscription.id}:{parent.id}",
                )
                queued += 1

    if get_org_setting(organization, AUTO_NOTIFY_LESSON_REMINDER_ENABLED):
        reminder_hours = get_org_setting(organization, AUTO_NOTIFY_LESSON_REMINDER_HOURS)
        target = timezone.now() + datetime.timedelta(hours=reminder_hours)
        local_target = target.astimezone(ZoneInfo(organization.timezone or "Asia/Almaty")).date()
        start, end = day_bounds_for_org(organization, local_target)
        lessons = (
            Lesson.objects.for_tenant(organization)
            .filter(status=Lesson.Status.SCHEDULED, starts_at__range=(start, end))
            .select_related("group", "group__branch", "room")
        )
        for lesson in lessons:
            local = lesson.starts_at.astimezone(ZoneInfo(organization.timezone or "Asia/Almaty"))
            group = lesson.group.name if lesson.group else "Индивидуальное занятие"
            branch = lesson.group.branch.name if lesson.group else ""
            place = " · ".join(
                part for part in (branch, lesson.room.name if lesson.room else "") if part
            )
            for child in lesson.participants():
                for parent in _contacts(child):
                    notify(
                        parent,
                        "lesson_reminder",
                        {
                            "child": child.full_name,
                            "group": group,
                            "when": local.strftime("%d.%m в %H:%M"),
                            "place": place,
                        },
                        dedup_key=(f"auto:lesson-reminder:{lesson.id}:{child.id}:{parent.id}"),
                    )
                    queued += 1
    return queued


def dispatch_daily(now=None) -> int:
    """Проверяется каждый час, но для каждого центра работает утром в 9."""
    now = now or timezone.now()
    queued = 0
    for organization in Organization.objects.filter(is_active=True, deleted_at__isnull=True):
        local = now.astimezone(ZoneInfo(organization.timezone or "Asia/Almaty"))
        if local.hour == 9:
            queued += dispatch_daily_for_organization(organization, today=local.date())
    return queued


def _change_line(lesson, tz) -> str:
    local = lesson.starts_at.astimezone(tz)
    group = lesson.group.name if lesson.group else "Индивидуальное занятие"
    when = local.strftime("%d.%m в %H:%M")
    if lesson.status == Lesson.Status.RESCHEDULED and lesson.rescheduled_to_id:
        moved = lesson.rescheduled_to.starts_at.astimezone(tz).strftime("%d.%m в %H:%M")
        return f"«{group}», {when}: перенесено на {moved}."
    reason = lesson.cancel_reason.strip()
    suffix = f" Причина: {reason}." if reason else ""
    return f"«{group}», {when}: отменено.{suffix}"


def dispatch_lesson_change(lesson_id) -> int:
    """После короткой задержки перепроверяет статус и собирает изменения за день."""
    lesson = (
        Lesson.objects.select_related("organization", "group", "rescheduled_to")
        .filter(pk=lesson_id)
        .first()
    )
    if not lesson or lesson.status not in (Lesson.Status.CANCELLED, Lesson.Status.RESCHEDULED):
        return 0
    organization = lesson.organization
    if not get_org_setting(organization, AUTO_NOTIFY_LESSON_CHANGES_ENABLED):
        return 0
    tz = ZoneInfo(organization.timezone or "Asia/Almaty")
    day = lesson.starts_at.astimezone(tz).date()
    start, end = day_bounds_for_org(organization, day)
    changed = list(
        Lesson.objects.for_tenant(organization)
        .filter(
            starts_at__range=(start, end),
            status__in=(Lesson.Status.CANCELLED, Lesson.Status.RESCHEDULED),
        )
        .select_related("group", "rescheduled_to")
    )
    by_child = defaultdict(list)
    for changed_lesson in changed:
        for child in changed_lesson.participants():
            by_child[child].append(changed_lesson)
    queued = 0
    for child, lessons in by_child.items():
        sorted_lessons = sorted(lessons, key=lambda item: item.starts_at)
        first = sorted_lessons[0]
        changes = "\n".join(_change_line(item, tz) for item in sorted_lessons)
        first_group = first.group.name if first.group else "Индивидуальное занятие"
        first_when = first.starts_at.astimezone(tz).strftime("%d.%m в %H:%M")
        for parent in _contacts(child):
            notify(
                parent,
                "lesson_cancelled",
                {
                    "child": child.full_name,
                    "changes": changes,
                    # Старые сохранённые шаблоны TRU-168 используют эти поля.
                    "group": first_group,
                    "when": first_when,
                    "note": changes,
                },
                dedup_key=(f"auto:lesson-change:{child.id}:{day.isoformat()}:{parent.id}"),
            )
            queued += 1
    return queued


def volume_preview(organization) -> dict:
    """Оценка типичной недели без создания сообщений."""
    debt = debtor_subscriptions(
        organization,
        min_age_days=get_org_setting(organization, DEBT_OVERDUE_DAYS_THRESHOLD),
    ).count()
    ending = expiring_subscriptions(organization).count()
    week_end = timezone.now() + datetime.timedelta(days=7)
    lessons = Lesson.objects.for_tenant(organization).filter(
        status=Lesson.Status.SCHEDULED,
        starts_at__gte=timezone.now(),
        starts_at__lt=week_end,
    )
    reminder_recipients = sum(lesson.participants().count() for lesson in lessons)
    return {
        "payment": debt,
        "subscription": ending,
        "lesson_changes": 0,
        "lesson_reminder": reminder_recipients,
        "total": debt + ending + reminder_recipients,
        "note": "Изменения расписания заранее неизвестны и в оценку не входят.",
    }
