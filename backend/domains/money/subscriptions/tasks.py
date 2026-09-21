from celery import shared_task

from .reconciliation import reconcile_all_active_subscriptions


@shared_task
def reconcile_balances_task() -> int:
    return reconcile_all_active_subscriptions()
