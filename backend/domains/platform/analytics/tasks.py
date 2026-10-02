from celery import shared_task

from .snapshots import snapshot_all


@shared_task
def snapshot_metrics_task() -> int:
    return snapshot_all()
