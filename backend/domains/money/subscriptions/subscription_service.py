"""
SubscriptionService — контракт №1 из TRU-8 (сторона владельца, домен
subscriptions), см. backend/docs/contracts.md. Вызывается из TRU-50 при
отметке посещаемости.

direction_id — обязательный параметр: при нескольких активных абонементах
ребёнка (разные направления) без него нет способа выбрать правильный
(см. TRU-58/59, Subscription.direction). Добавлен до появления первого
вызывающего кода (TRU-50) — без обратной несовместимости.
"""

import enum
import uuid
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from .models import LessonConsumption, Subscription, SubscriptionLedgerEntry
from .subscriptions import add_ledger_entry


class ConsumeOutcome(enum.Enum):
    CONSUMED = "consumed"
    NO_ACTIVE_SUBSCRIPTION = "no_active_subscription"
    SUBSCRIPTION_EXHAUSTED = "subscription_exhausted"
    SUBSCRIPTION_FROZEN = "subscription_frozen"
    RULE_FORBIDS = "rule_forbids"


@dataclass
class ConsumeResult:
    outcome: ConsumeOutcome
    subscription_id: uuid.UUID | None = None


def _check_type_rules(subscription: Subscription) -> bool:
    """Точка расширения под rules из TRU-57. Реальные правила True Ballet
    не выяснены (Discovery, вопрос №1) — пока всегда разрешает списание."""
    return True


def _pick_subscription(child, direction_id):
    return (
        Subscription.objects.for_tenant(child.organization)
        .filter(
            child=child, direction_id=direction_id,
            status__in=[Subscription.Status.ACTIVE, Subscription.Status.FROZEN],
        )
        .order_by("ends_on")
        .first()
    )


class SubscriptionService:
    @staticmethod
    @transaction.atomic
    def consume(child_id, lesson_id, direction_id) -> ConsumeResult:
        from domains.people.clients.models import Child

        child = Child.objects.get(id=child_id)

        existing = LessonConsumption.objects.filter(
            child_id=child_id, lesson_id=lesson_id, reverted_at__isnull=True,
        ).first()
        if existing:
            return ConsumeResult(ConsumeOutcome.CONSUMED, existing.subscription_id)

        subscription = _pick_subscription(child, direction_id)
        if subscription is None:
            return ConsumeResult(ConsumeOutcome.NO_ACTIVE_SUBSCRIPTION)
        if subscription.status == Subscription.Status.FROZEN:
            return ConsumeResult(ConsumeOutcome.SUBSCRIPTION_FROZEN, subscription.id)
        if not subscription.subscription_type_version.is_unlimited and subscription.sessions_remaining_cache <= 0:
            return ConsumeResult(ConsumeOutcome.SUBSCRIPTION_EXHAUSTED, subscription.id)
        if not _check_type_rules(subscription):
            return ConsumeResult(ConsumeOutcome.RULE_FORBIDS, subscription.id)

        entry = add_ledger_entry(subscription, kind=SubscriptionLedgerEntry.Kind.CONSUMPTION, delta=-1)
        LessonConsumption.objects.create(
            organization=child.organization, child=child, lesson_id=lesson_id,
            subscription=subscription, ledger_entry=entry,
        )
        return ConsumeResult(ConsumeOutcome.CONSUMED, subscription.id)

    @staticmethod
    @transaction.atomic
    def revert(child_id, lesson_id) -> bool:
        """True — реально откатили; False — для этой пары не было активного
        списания (идемпотентно, не создаёт лишних начислений)."""
        record = LessonConsumption.objects.filter(
            child_id=child_id, lesson_id=lesson_id, reverted_at__isnull=True,
        ).first()
        if record is None:
            return False

        add_ledger_entry(
            record.subscription, kind=SubscriptionLedgerEntry.Kind.MANUAL_ADJUSTMENT,
            delta=1, comment=f"Возврат по занятию {lesson_id}",
        )
        record.reverted_at = timezone.now()
        record.save(update_fields=["reverted_at"])
        return True