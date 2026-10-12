"""
Автостатусы абонемента (ТЗ п. 4.4). "Заканчивается" — НЕ значение
Subscription.status, а результат вычисления на лету: он не блокирует
списание (в отличие от frozen/expired/exhausted), это подсказка для
экрана продлений, а не состояние в терминах consume()/ALLOWED_STATUS_TRANSITIONS.

Пороги — только через get_org_setting() (TRU-23), никаких чисел здесь.
"""

import logging

from django.db.models import Exists, OuterRef

from domains.platform.core.utils import today_for_org
from domains.platform.tenants.models import Organization
from domains.platform.tenants.org_settings import RULE_RENEWAL_OFFER_ENABLED, get_org_setting

from .freezes import finish_freeze, freezes_covering, start_freeze
from .models import Subscription, SubscriptionFreeze
from .renewals import is_ending_soon
from .subscriptions import transition_status

logger = logging.getLogger(__name__)

ENDING_SOON = "ending_soon"  # только для отображения, никогда не пишется в Subscription.status
DISPLAY_LABELS = {ENDING_SOON: "Заканчивается", **dict(Subscription.Status.choices)}


def suggest_renewal(subscription: Subscription) -> None:
    """Точка вызова автозадачи «предложить продление» (ТЗ п. 5.2, TRU-108).
    Ночная задача зовёт её КАЖДУЮ ночь для каждого «заканчивающегося»
    абонемента — идемпотентность через source_key на Subscription.id:
    пока задача по этому абонементу открыта, вторая не создаётся."""
    from domains.platform.tasks.models import Task
    from domains.platform.tasks.services import create_task

    organization = subscription.organization
    if not get_org_setting(organization, RULE_RENEWAL_OFFER_ENABLED):
        return
    create_task(
        type=Task.Type.RENEWAL_OFFER,
        assignee=None,
        due_date=None,
        subject=f"Предложить продление: {subscription.child.full_name}",
        organization=organization,
        source=Task.Source.AUTO,
        branch=subscription.branch,
        child=subscription.child,
        source_key=f"renewal_offer:{subscription.id}",
    )


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

    # Статус «заморожен» — ровно пока сегодня внутри какой-то заморозки
    # (TRU-132). Заморозка закончилась — размораживаем, но не если уже идёт
    # следующая; заморозка, оформленная заранее, началась — замораживаем.
    # Так же исправляются абонементы, замороженные раньше срока до TRU-132.
    in_freeze = Exists(
        freezes_covering(SubscriptionFreeze.objects.filter(subscription=OuterRef("pk")), today)
    )
    finished = subscriptions.filter(~in_freeze, status=Subscription.Status.FROZEN)
    for subscription in finished.iterator():
        changed += safely(finish_freeze, subscription)

    started = subscriptions.filter(in_freeze, status=Subscription.Status.ACTIVE)
    for subscription in started.iterator():
        changed += safely(start_freeze, subscription)

    return changed
