from celery import shared_task

from domains.money.subscriptions.debt import create_tasks_for_overdue_debt


@shared_task
def create_lead_stale_tasks_task() -> int:
    from domains.platform.leads.rules import create_tasks_for_stale_leads

    return create_tasks_for_stale_leads()


@shared_task
def create_debt_reminder_tasks_task() -> int:
    return create_tasks_for_overdue_debt()
