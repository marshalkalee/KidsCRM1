"""
Автостатусы абонемента (ТЗ п. 4.4). "Заканчивается" — НЕ значение
Subscription.status, а результат вычисления на лету: он не блокирует
списание (в отличие от frozen/expired/exhausted), это подсказка для
экрана продлений, а не состояние в терминах consume()/ALLOWED_STATUS_TRANSITIONS.

Пороги — только через get_org_setting() (TRU-23), никаких чисел здесь.
"""

from datetime import date

from domains.platform.tenants.org_settings import (
    SUBSCRIPTION_ENDING_DAYS_THRESHOLD,
    SUBSCRIPTION_ENDING_LESSONS_THRESHOLD,
    get_org_setting,
)

from .models import Subscription
from .subscriptions import transition_status

ENDING_SOON = "ending_soon"  # только для отображения, никогда не пишется в Subscription.status


def suggest_renewal(subscription: Subscription) -> None:
    """Точка вызова автозадачи «предложить продление» (ТЗ п. 5.2).
    Сама задача — M2 (домен tasks ещё не существует). На M1 — заглушка."""


def get_display_status(subscription: Subscription) -> str:
    """Единственное место, решающее, что показать. Карточка ребёнка, список
    и экран продлений обязаны звать эту функцию, а не вычислять условие
    каждый по-своему — иначе экраны разъедутся (критерий приёмки)."""
    if subscription.status != Subscription.Status.ACTIVE:
        return subscription.status

    days_left = (subscription.ends_on - date.today()).days
    lessons_left = subscription.sessions_remaining_cache

    days_threshold = get_org_setting(subscription.organization, SUBSCRIPTION_ENDING_DAYS_THRESHOLD)
    lessons_threshold = get_org_setting(
        subscription.organization, SUBSCRIPTION_ENDING_LESSONS_THRESHOLD
    )

    ending_by_days = days_left <= days_threshold
    ending_by_lessons = lessons_left is not None and lessons_left <= lessons_threshold
    if ending_by_days or ending_by_lessons:
        return ENDING_SOON
    return Subscription.Status.ACTIVE


def update_all_subscription_statuses() -> int:
    """Фоновая задача: абонемент истекает по дате/занятиям, даже если с ним
    ничего не делали — статус должен смениться сам, без клика человека."""
    today = date.today()
    changed = 0

    expiring = Subscription.objects.filter(
        status__in=[Subscription.Status.ACTIVE, Subscription.Status.FROZEN],
        ends_on__lt=today,
    ).select_related("organization")
    for subscription in expiring.iterator():
        transition_status(subscription, Subscription.Status.EXPIRED)
        suggest_renewal(subscription)
        changed += 1

    exhausted = Subscription.objects.filter(
        status=Subscription.Status.ACTIVE,
        subscription_type_version__is_unlimited=False,
        sessions_remaining_cache__lte=0,
    ).select_related("organization")
    for subscription in exhausted.iterator():
        transition_status(subscription, Subscription.Status.EXHAUSTED)
        suggest_renewal(subscription)
        changed += 1

    still_active = Subscription.objects.filter(status=Subscription.Status.ACTIVE).select_related(
        "organization"
    )
    for subscription in still_active.iterator():
        if get_display_status(subscription) == ENDING_SOON:
            suggest_renewal(subscription)

    return changed
