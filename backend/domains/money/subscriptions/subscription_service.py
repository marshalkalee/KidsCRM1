"""
SubscriptionService — контракт №1 из TRU-8 (сторона владельца, домен
subscriptions), см. backend/docs/contracts.md. Вызывается из TRU-50 при
отметке посещаемости.

direction_id — обязательный параметр: при нескольких активных абонементах
ребёнка (разные направления) без него нет способа выбрать правильный
(см. TRU-58/59, Subscription.direction). Добавлен до появления первого
вызывающего кода (TRU-50) — без обратной несовместимости.

lesson_date (TRU-130) — дата занятия в часовом поясе центра: списывать
можно, только если она попадает в starts_on ≤ дата ≤ ends_on. Ночная задача
переводит абонемент в «истёк» не сразу, поэтому статуса ACTIVE мало.
Необязательный: без него берётся «сегодня» центра.
"""

import enum
import uuid
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from domains.platform.core.utils import today_for_org

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


def _has_sessions(subscription: Subscription) -> bool:
    return (
        subscription.subscription_type_version.is_unlimited
        or (subscription.sessions_remaining_cache or 0) > 0
    )


def _lock_candidates(child, direction_id, lesson_date):
    """Абонементы направления, чей срок покрывает дату занятия, под
    блокировкой строк до конца транзакции (TRU-130: два одновременных
    consume на последнем занятии иначе оба видят остаток 1). Порядок
    ends_on, id одинаков у всех вызовов — блокировки берутся в одном
    порядке, без взаимоблокировок."""
    return list(
        Subscription.objects.for_tenant(child.organization)
        .select_for_update(of=("self",))
        .select_related("subscription_type_version")
        .filter(
            child=child,
            direction_id=direction_id,
            status__in=[Subscription.Status.ACTIVE, Subscription.Status.FROZEN],
            starts_on__lte=lesson_date,
            ends_on__gte=lesson_date,
        )
        .order_by("ends_on", "id")
    )


def _pick_subscription(candidates):
    """Сначала активный с остатком (раньше заканчивается — раньше
    списываем), затем активный без остатка (→ «исчерпан»), и только если
    активных нет — замороженный (→ «заморожен»). TRU-130: замороженный
    с более ранним ends_on не должен заслонять активный."""
    active = [s for s in candidates if s.status == Subscription.Status.ACTIVE]
    with_sessions = [s for s in active if _has_sessions(s)]
    if with_sessions:
        return with_sessions[0]
    if active:
        return active[0]
    return candidates[0] if candidates else None


class SubscriptionService:
    @staticmethod
    @transaction.atomic
    def consume(child_id, lesson_id, direction_id, lesson_date=None) -> ConsumeResult:
        from domains.people.clients.models import Child

        child = Child.objects.get(id=child_id)

        existing = LessonConsumption.objects.filter(
            child_id=child_id,
            lesson_id=lesson_id,
            reverted_at__isnull=True,
        ).first()
        if existing:
            return ConsumeResult(ConsumeOutcome.CONSUMED, existing.subscription_id)

        if lesson_date is None:
            lesson_date = today_for_org(child.organization)
        subscription = _pick_subscription(_lock_candidates(child, direction_id, lesson_date))
        if subscription is None:
            return ConsumeResult(ConsumeOutcome.NO_ACTIVE_SUBSCRIPTION)
        if subscription.status == Subscription.Status.FROZEN:
            return ConsumeResult(ConsumeOutcome.SUBSCRIPTION_FROZEN, subscription.id)
        if not _has_sessions(subscription):
            return ConsumeResult(ConsumeOutcome.SUBSCRIPTION_EXHAUSTED, subscription.id)
        if not _check_type_rules(subscription):
            return ConsumeResult(ConsumeOutcome.RULE_FORBIDS, subscription.id)

        entry = add_ledger_entry(
            subscription, kind=SubscriptionLedgerEntry.Kind.CONSUMPTION, delta=-1
        )
        LessonConsumption.objects.create(
            organization=child.organization,
            child=child,
            lesson_id=lesson_id,
            subscription=subscription,
            ledger_entry=entry,
        )
        return ConsumeResult(ConsumeOutcome.CONSUMED, subscription.id)

    @staticmethod
    @transaction.atomic
    def revert(child_id, lesson_id) -> bool:
        """True — реально откатили; False — для этой пары не было активного
        списания (идемпотентно, не создаёт лишних начислений)."""
        record = (
            LessonConsumption.objects.select_for_update()
            .filter(
                child_id=child_id,
                lesson_id=lesson_id,
                reverted_at__isnull=True,
            )
            .first()
        )
        if record is None:
            return False

        subscription = (
            Subscription.objects.select_for_update(of=("self",))
            .select_related("subscription_type_version")
            .get(pk=record.subscription_id)
        )
        add_ledger_entry(
            subscription,
            kind=SubscriptionLedgerEntry.Kind.LESSON_REVERT,
            delta=1,
            comment=f"Возврат по занятию {lesson_id}",
        )
        _reactivate_if_sessions_left(subscription)
        record.reverted_at = timezone.now()
        record.save(update_fields=["reverted_at"])
        return True


def _reactivate_if_sessions_left(subscription: Subscription) -> None:
    """TRU-130: ночная задача перевела абонемент в «исчерпан», а занятие
    вернули — абонемент снова рабочий. Переход EXHAUSTED → ACTIVE нарочно
    не внесён в ALLOWED_STATUS_TRANSITIONS: вручную исчерпанный абонемент
    не оживить, только откатом списания."""
    if subscription.status == Subscription.Status.EXHAUSTED and _has_sessions(subscription):
        subscription.status = Subscription.Status.ACTIVE
        subscription.save(update_fields=["status"])
