"""
Работа с остатком — вся запись через add_ledger_entry(), никогда напрямую
sessions_remaining_cache (ТЗ п. 3.2: кэш, не источник правды).
"""

from django.db import transaction
from django.db.models import Sum

from .models import Subscription, SubscriptionLedgerEntry


def recompute_sessions_remaining(subscription: Subscription) -> int | None:
    if subscription.subscription_type_version.is_unlimited:
        return None
    return subscription.ledger_entries.aggregate(total=Sum("delta"))["total"] or 0


@transaction.atomic
def add_ledger_entry(subscription: Subscription, *, kind: str, delta: int, comment: str = "") -> SubscriptionLedgerEntry:
    entry = SubscriptionLedgerEntry.objects.create(
        organization=subscription.organization, subscription=subscription,
        kind=kind, delta=delta, comment=comment,
    )
    subscription.sessions_remaining_cache = recompute_sessions_remaining(subscription)
    subscription.save(update_fields=["sessions_remaining_cache"])
    return entry


def transition_status(subscription: Subscription, new_status: str) -> None:
    if not subscription.can_transition_to(new_status):
        raise ValueError(f"Недопустимый переход {subscription.status} -> {new_status}")
    subscription.status = new_status
    subscription.save(update_fields=["status"])


def get_active_subscription_for_direction(child, direction):
    """Критерий приёмки: ребёнок с балетом и гимнастикой — выбор по
    direction, активным статусом, у кого раньше ends_on — тот и используется."""
    return (
        Subscription.objects.for_tenant(child.organization)
        .filter(child=child, direction=direction, status=Subscription.Status.ACTIVE)
        .order_by("ends_on")
        .first()
    )