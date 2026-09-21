from celery import shared_task

from .reconciliation import reconcile_all_active_subscriptions
from .statuses import update_all_subscription_statuses


@shared_task
def reconcile_balances_task() -> int:
    return reconcile_all_active_subscriptions()


@shared_task
def update_subscription_statuses_task() -> int:
    return update_all_subscription_statuses()
