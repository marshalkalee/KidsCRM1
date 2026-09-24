"""
Заморозка/разморозка (ТЗ п. 4.4). Использует SubscriptionFreeze (TRU-58) —
там были только поля для истории, здесь — применение: сдвиг ends_on, лимит
из rules.freezes_per_year, досрочная разморозка, аудит.

Поведение consume() во время заморозки уже решено в TRU-60 (SUBSCRIPTION_FROZEN,
без списания) — здесь не трогаем, только сам процесс заморозки/разморозки.

Лимит "сколько заморозок в год" не выяснен (Discovery, вопрос №1, ТЗ п. 13.1).
При отсутствии rules.freezes_per_year ограничения нет — до ответа True Ballet.
"""

from datetime import date, timedelta

from django.db import transaction

from domains.platform.core.audit import AuditLog

from .models import Subscription, SubscriptionFreeze
from .subscriptions import transition_status


def _freezes_used_last_year(subscription: Subscription) -> int:
    cutoff = date.today() - timedelta(days=365)
    return subscription.freezes.filter(starts_on__gte=cutoff).count()


@transaction.atomic
def freeze_subscription(
    subscription: Subscription,
    *,
    actor,
    starts_on: date,
    ends_on: date,
    reason: str = "",
) -> SubscriptionFreeze:
    limit = subscription.subscription_type_version.rules.get("freezes_per_year")
    if limit is not None and _freezes_used_last_year(subscription) >= limit:
        raise ValueError("Превышен лимит заморозок для этого абонемента за год")

    before = {"ends_on": subscription.ends_on.isoformat()}
    freeze = SubscriptionFreeze.objects.create(
        organization=subscription.organization,
        subscription=subscription,
        starts_on=starts_on,
        ends_on=ends_on,
        reason=reason,
    )
    subscription.ends_on += timedelta(days=(ends_on - starts_on).days)
    subscription.save(update_fields=["ends_on"])
    transition_status(subscription, Subscription.Status.FROZEN)

    AuditLog.record(
        actor=actor,
        action=AuditLog.Action.FREEZE,
        entity=subscription,
        before=before,
        after={"ends_on": subscription.ends_on.isoformat(), "freeze_id": str(freeze.id)},
    )
    return freeze


@transaction.atomic
def unfreeze_subscription(
    subscription: Subscription,
    *,
    actor=None,
    actual_end_date: date | None = None,
) -> SubscriptionFreeze:
    freeze = subscription.freezes.filter(ends_on__gte=date.today()).order_by("-starts_on").first()
    if freeze is None:
        raise ValueError("Активной заморозки не найдено")

    actual_end_date = actual_end_date or freeze.ends_on
    planned_days = (freeze.ends_on - freeze.starts_on).days
    actual_days = (actual_end_date - freeze.starts_on).days
    adjustment = actual_days - planned_days  # отрицательное при досрочной разморозке

    before = {"ends_on": subscription.ends_on.isoformat()}
    freeze.ends_on = actual_end_date
    freeze.save(update_fields=["ends_on"])

    subscription.ends_on += timedelta(days=adjustment)
    subscription.save(update_fields=["ends_on"])
    transition_status(subscription, Subscription.Status.ACTIVE)

    AuditLog.record(
        actor=actor,
        action=AuditLog.Action.UNFREEZE,
        entity=subscription,
        before=before,
        after={"ends_on": subscription.ends_on.isoformat()},
    )
    return freeze
