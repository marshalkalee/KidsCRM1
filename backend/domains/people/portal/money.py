"""
Абонемент и оплаты в кабинете (TRU-139), только просмотр.

Остаток объясняется журналом списаний — тем же, что у администратора
(SubscriptionLedgerEntry): какое занятие списалось и когда. Родителю не
уходят комментарии сотрудников, цена до скидки и отменённые оплаты:
- цена — итоговая (price), без механики скидок центра;
- журнал — без служебных комментариев, «Корректировка» без причины;
- оплаты — только подтверждённые и не отменённые (отмена — исправление
  ошибки администратора, родителю она ничего не говорит).

Как оплатить: онлайн-оплаты в кабинете нет (ТЗ п. 12). Показываем
реквизиты Kaspi центра и телефон филиала с кнопкой WhatsApp.
"""

from django.utils import timezone

from domains.money.payments.models import Payment
from domains.money.subscriptions.models import (
    LessonConsumption,
    Subscription,
    SubscriptionLedgerEntry,
)
from domains.scheduling.groups.models import GroupMembership
from domains.scheduling.schedule.models import Lesson

from .summary import current_subscription, subscription_row

LEDGER_LABELS = {
    SubscriptionLedgerEntry.Kind.INITIAL_GRANT: "Покупка абонемента",
    SubscriptionLedgerEntry.Kind.EXTENSION: "Продление",
}


def _tz(organization):
    return timezone.zoneinfo.ZoneInfo(organization.timezone or "Asia/Almaty")


def ledger(subscription):
    """Журнал списаний с остатком после каждой строки, свежие сверху."""
    tz = _tz(subscription.organization)
    entries = list(subscription.ledger_entries.order_by("created_at", "id"))
    consumption = {
        c.ledger_entry_id: c for c in LessonConsumption.objects.filter(ledger_entry__in=entries)
    }
    lessons = {
        lesson.id: lesson
        for lesson in Lesson.objects.filter(
            id__in=[c.lesson_id for c in consumption.values()]
        ).select_related("group")
    }
    rows, balance = [], 0
    for entry in entries:
        balance += entry.delta
        row = {
            "date": entry.created_at.astimezone(tz).isoformat(),
            "delta": entry.delta,
            "balance": balance,
            "lesson": None,
        }
        if entry.kind == SubscriptionLedgerEntry.Kind.CONSUMPTION:
            record = consumption.get(entry.id)
            lesson = lessons.get(record.lesson_id) if record else None
            row["label"] = "Занятие"
            if lesson:
                row["lesson"] = {
                    "starts_at": lesson.starts_at.astimezone(tz).isoformat(),
                    "group": lesson.group.name if lesson.group_id else "",
                }
            row["reverted"] = bool(record and record.reverted_at)
        elif entry.kind == SubscriptionLedgerEntry.Kind.MANUAL_ADJUSTMENT:
            row["label"] = "Возврат занятия" if entry.delta > 0 else "Корректировка"
        else:
            row["label"] = LEDGER_LABELS.get(entry.kind, entry.get_kind_display())
        rows.append(row)
    return list(reversed(rows))


def _history_row(subscription):
    row = subscription_row(subscription)
    row["price"] = str(subscription.price)
    row["direction"] = subscription.direction.name if subscription.direction_id else ""
    return row


def payments(child):
    tz = _tz(child.organization)
    rows = (
        Payment.objects.filter(
            subscription__child=child,
            status=Payment.Status.CONFIRMED,
            deleted_at__isnull=True,
        )
        .select_related("subscription__subscription_type_version")
        .order_by("-paid_at")
    )
    return [
        {
            "id": str(p.id),
            "paid_at": p.paid_at.astimezone(tz).isoformat(),
            "amount": str(p.amount),
            "method": p.method,
            "method_display": p.get_method_display(),
            "subscription": p.subscription.subscription_type_version.name,
        }
        for p in rows
    ]


def contacts(child):
    """Куда писать об оплате: телефоны филиалов, где ребёнок занимается
    (по текущим группам), иначе — все филиалы центра с телефоном."""
    branches = {
        m.group.branch
        for m in GroupMembership.objects.filter(child=child, left_at__isnull=True).select_related(
            "group__branch"
        )
        if m.group.branch_id
    }
    if not branches:
        branches = set(
            child.organization.branch_set.filter(deleted_at__isnull=True, is_active=True)
        )
    rows = []
    for branch in sorted(branches, key=lambda b: b.name):
        if branch.phone:
            digits = "".join(ch for ch in branch.phone if ch.isdigit())
            rows.append(
                {
                    "branch": branch.name,
                    "phone": branch.phone,
                    "whatsapp_url": f"https://wa.me/{digits}",
                }
            )
    return rows


def money(child):
    from domains.money.subscriptions.debt import debt_by_child

    organization = child.organization
    current = current_subscription(child)
    history = (
        Subscription.objects.filter(child=child, deleted_at__isnull=True)
        .select_related("subscription_type_version", "organization", "direction")
        .order_by("-starts_on")
    )
    debt = debt_by_child(organization, [child.id]).get(child.id, 0)
    return {
        "current": _history_row(current) if current else None,
        "ledger": ledger(current) if current else [],
        "history": [_history_row(s) for s in history if not current or s.pk != current.pk],
        "payments": payments(child),
        "to_pay": str(debt),
        "how_to_pay": {"contacts": contacts(child)},
    }
