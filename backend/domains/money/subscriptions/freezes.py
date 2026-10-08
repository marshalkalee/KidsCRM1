"""
Заморозка/разморозка (ТЗ п. 4.4). Использует SubscriptionFreeze (TRU-58) —
там были только поля для истории, здесь — применение: сдвиг ends_on, лимит
из rules.freezes_per_year, досрочная разморозка, аудит.

Поведение consume() во время заморозки уже решено в TRU-60 (SUBSCRIPTION_FROZEN,
без списания) — здесь не трогаем, только сам процесс заморозки/разморозки.

Лимит "сколько заморозок в год" не выяснен (Discovery, вопрос №1, ТЗ п. 13.1).
При отсутствии rules.freezes_per_year ограничения нет — до ответа True Ballet.

TRU-132: статус FROZEN — только пока сегодняшний день внутри заморозки
[starts_on, ends_on] (оба конца включительно). Заморозка с будущим стартом
оставляет абонемент действующим: ночная задача (statuses) сама переведёт его
в FROZEN в день начала и вернёт в ACTIVE после окончания. Заморозки одного
абонемента не пересекаются: иначе срок продлился бы дважды за одни и те же дни.
"""

from datetime import date, timedelta

from django.db import transaction
from django.db.models import F, Q, QuerySet

from domains.platform.core.audit import AuditLog
from domains.platform.core.utils import today_for_org

from .models import Subscription, SubscriptionFreeze
from .subscriptions import transition_status


def _freezes_used_last_year(subscription: Subscription) -> int:
    cutoff = today_for_org(subscription.organization) - timedelta(days=365)
    return subscription.freezes.filter(starts_on__gte=cutoff).count()


def _effective(freezes: QuerySet) -> QuerySet:
    # Заморозка нулевой длины — та, что разморозили в день её начала: дней не
    # дала, срок не сдвинула, ни статус, ни новые заморозки не блокирует.
    return freezes.filter(deleted_at__isnull=True).exclude(ends_on=F("starts_on"))


def freezes_covering(freezes: QuerySet, day: date) -> QuerySet:
    """Заморозки, внутри которых лежит день. ends_on пустой — у старых записей:
    заморозка без конца, считаем идущей."""
    return _effective(freezes).filter(
        Q(ends_on__isnull=True) | Q(ends_on__gte=day), starts_on__lte=day
    )


def _check_no_overlap(
    subscription: Subscription, starts_on: date, ends_on: date, *, exclude=None
) -> None:
    overlapping = _effective(subscription.freezes.all()).filter(
        Q(ends_on__isnull=True) | Q(ends_on__gte=starts_on), starts_on__lte=ends_on
    )
    if exclude is not None:
        overlapping = overlapping.exclude(pk=exclude.pk)
    other = overlapping.order_by("starts_on").first()
    if other is not None:
        until = other.ends_on.strftime("%d.%m.%Y") if other.ends_on else "без даты окончания"
        raise ValueError(
            "Даты пересекаются с другой заморозкой этого абонемента: "
            f"{other.starts_on:%d.%m.%Y} – {until}"
        )


def _lock(subscription: Subscription) -> None:
    # Две заморозки одновременно не должны обе пройти проверку пересечений:
    # блокируем строку абонемента и перечитываем её (статус, срок) уже под замком.
    Subscription.objects.select_for_update().filter(pk=subscription.pk).first()
    subscription.refresh_from_db()


@transaction.atomic
def freeze_subscription(
    subscription: Subscription,
    *,
    actor,
    starts_on: date,
    ends_on: date,
    reason: str = "",
) -> SubscriptionFreeze:
    if ends_on <= starts_on:
        raise ValueError("Дата окончания заморозки должна быть позже даты начала")
    _lock(subscription)
    if subscription.status != Subscription.Status.ACTIVE:
        raise ValueError(
            "Заморозить можно только действующий абонемент, "
            f"сейчас он: «{subscription.get_status_display()}»"
        )
    limit = subscription.subscription_type_version.rules.get("freezes_per_year")
    if limit is not None and _freezes_used_last_year(subscription) >= limit:
        raise ValueError("Превышен лимит заморозок для этого абонемента за год")
    _check_no_overlap(subscription, starts_on, ends_on)

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
    # Будущая заморозка (и уже закончившаяся, задним числом) статус не меняет:
    # до её начала занятия списываются как обычно.
    if starts_on <= today_for_org(subscription.organization) <= ends_on:
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
    _lock(subscription)
    today = today_for_org(subscription.organization)
    # Идущая заморозка, а не самая поздняя: самой поздней может быть
    # запланированная на будущее (TRU-132).
    freeze = freezes_covering(subscription.freezes.all(), today).order_by("-starts_on").first()
    if freeze is None:
        raise ValueError("Активной заморозки не найдено")

    # Без даты — разморозить сегодня, как кнопка «Разморозить» в карточке.
    actual_end_date = actual_end_date or today
    # Раньше начала заморозки закончить нельзя — иначе срок уедет назад.
    actual_end_date = max(actual_end_date, freeze.starts_on)
    if freeze.ends_on is not None and actual_end_date > freeze.ends_on:
        # Продление заморозки не должно наехать на следующую.
        _check_no_overlap(subscription, freeze.starts_on, actual_end_date, exclude=freeze)
    planned_days = (freeze.ends_on - freeze.starts_on).days
    actual_days = (actual_end_date - freeze.starts_on).days
    adjustment = actual_days - planned_days  # отрицательное при досрочной разморозке

    before = {"ends_on": subscription.ends_on.isoformat()}
    freeze.ends_on = actual_end_date
    freeze.save(update_fields=["ends_on"])

    subscription.ends_on += timedelta(days=adjustment)
    subscription.save(update_fields=["ends_on"])
    # Разморозка будущим числом лишь переносит конец заморозки: до него
    # абонемент заморожен, ночная задача разморозит его сама (иначе она же
    # заморозила бы его обратно, раз заморозка ещё идёт).
    if actual_end_date <= today:
        transition_status(subscription, Subscription.Status.ACTIVE)

    AuditLog.record(
        actor=actor,
        action=AuditLog.Action.UNFREEZE,
        entity=subscription,
        before=before,
        after={"ends_on": subscription.ends_on.isoformat()},
    )
    return freeze


@transaction.atomic
def start_freeze(subscription: Subscription) -> None:
    """
    Наступил день начала заморозки, оформленной заранее (ночная задача,
    statuses.update_all_subscription_statuses). Срок не сдвигаем: он сдвинут
    при оформлении.
    """
    transition_status(subscription, Subscription.Status.FROZEN)
    AuditLog.record(
        actor=None,
        action=AuditLog.Action.FREEZE,
        entity=subscription,
        after={"ends_on": subscription.ends_on.isoformat(), "reason": "заморозка началась"},
    )


@transaction.atomic
def finish_freeze(subscription: Subscription) -> None:
    """
    Заморозка закончилась по плану — абонемент снова активен (ночная задача,
    statuses.update_all_subscription_statuses). Срок не сдвигаем: вся длина
    заморозки уже добавлена к ends_on при заморозке. unfreeze_subscription
    здесь не подходит — она ищет заморозку, которая ещё идёт, и для
    закончившейся падала с «Активной заморозки не найдено».
    """
    transition_status(subscription, Subscription.Status.ACTIVE)
    AuditLog.record(
        actor=None,
        action=AuditLog.Action.UNFREEZE,
        entity=subscription,
        after={"ends_on": subscription.ends_on.isoformat(), "reason": "заморозка закончилась"},
    )
