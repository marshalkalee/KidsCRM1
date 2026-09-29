"""
Автостатусы абонемента (ТЗ п. 4.4). "Заканчивается" — НЕ значение
Subscription.status, а результат вычисления на лету: он не блокирует
списание (в отличие от frozen/expired/exhausted), это подсказка для
экрана продлений, а не состояние в терминах consume()/ALLOWED_STATUS_TRANSITIONS.

Пороги — только через get_org_setting() (TRU-23), никаких чисел здесь.
"""

import logging

from domains.platform.core.utils import today_for_org
from domains.platform.tenants.models import Organization

from .freezes import finish_freeze
from .models import Subscription
from .renewals import is_ending_soon
from .subscriptions import transition_status

logger = logging.getLogger(__name__)

ENDING_SOON = "ending_soon"  # только для отображения, никогда не пишется в Subscription.status
DISPLAY_LABELS = {ENDING_SOON: "Заканчивается", **dict(Subscription.Status.choices)}


def suggest_renewal(subscription: Subscription) -> None:
    """Точка вызова автозадачи «предложить продление» (ТЗ п. 5.2).
    Сама задача — M2 (TRU-108), на M1 — заглушка. Ночная задача зовёт её
    КАЖДУЮ ночь для каждого «заканчивающегося» абонемента, поэтому то, что
    сюда подключат, обязано быть идемпотентным — как create_renewal_lead."""


def get_display_status(subscription: Subscription, today=None) -> str:
    """Что показать: статус абонемента или «заканчивается». Условие — то же,
    что у фильтра списка детей и экрана «Продления» (renewals.is_ending_soon)."""
    if is_ending_soon(subscription, today):
        return ENDING_SOON
    return subscription.status


def update_all_subscription_statuses() -> int:
    """Фоновая задача: абонемент истекает по дате/занятиям, даже если с ним
    ничего не делали — статус должен смениться сам, без клика человека.
    «Сегодня» — у каждого центра своё (часовой пояс организации)."""
    changed = 0
    for organization in Organization.objects.all():
        changed += _update_organization(organization, today_for_org(organization))
    return changed


def _update_organization(organization, today) -> int:
    changed = 0

    def safely(action, subscription):
        # Один сбойный абонемент не должен обрывать ночную задачу для всех
        # остальных — ошибку в лог, идём дальше.
        try:
            action(subscription)
            return True
        except Exception:
            logger.exception("Автостатус абонемента %s не обновлён", subscription.pk)
            return False

    def expire(subscription):
        transition_status(subscription, Subscription.Status.EXPIRED)
        suggest_renewal(subscription)

    def exhaust(subscription):
        transition_status(subscription, Subscription.Status.EXHAUSTED)
        suggest_renewal(subscription)

    subscriptions = Subscription.objects.for_tenant(organization).select_related(
        "organization", "subscription_type_version"
    )
    expiring = subscriptions.filter(
        status__in=[Subscription.Status.ACTIVE, Subscription.Status.FROZEN],
        ends_on__lt=today,
    )
    for subscription in expiring.iterator():
        changed += safely(expire, subscription)

    exhausted = subscriptions.filter(
        status=Subscription.Status.ACTIVE,
        subscription_type_version__is_unlimited=False,
        sessions_remaining_cache__lte=0,
    )
    for subscription in exhausted.iterator():
        changed += safely(exhaust, subscription)

    for subscription in subscriptions.filter(status=Subscription.Status.ACTIVE).iterator():
        if is_ending_soon(subscription, today):
            suggest_renewal(subscription)

    # Заморозка закончилась — по ПОСЛЕДНЕЙ заморозке: старая закончившаяся
    # при новой, ещё идущей, не должна размораживать абонемент.
    for subscription in subscriptions.filter(status=Subscription.Status.FROZEN).iterator():
        latest = subscription.freezes.order_by("-starts_on").first()
        if latest is not None and latest.ends_on is not None and latest.ends_on < today:
            changed += safely(finish_freeze, subscription)

    return changed
