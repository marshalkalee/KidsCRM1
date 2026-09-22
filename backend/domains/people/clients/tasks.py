"""
Импорт файла — фоновая задача (ТЗ п. 10.1), не HTTP-запрос: на файле в
тысячи строк ChildService.find_duplicates() на каждую новую семью не
укладывается в бюджет одного запроса. Строки на момент постановки в
очередь уже распознаны/провалидированы (import_views.py,
ImportRow.to_dict()) — здесь только дедуп (resolve_rows) и создание
записей (execute_import).
"""

from celery import shared_task
from django.utils import timezone

from .import_service import ImportRow, execute_import, resolve_rows
from .models import ImportJob


@shared_task
def run_import_job(job_id: str) -> None:
    job = ImportJob.objects.get(pk=job_id)
    job.status = ImportJob.Status.RUNNING
    job.save(update_fields=["status"])

    try:
        rows = [ImportRow.from_dict(data) for data in job.rows_payload]
        resolve_rows(job.organization, rows)
        result = execute_import(job.organization, rows)

        job.created_count = result.created
        job.attached_count = result.attached_to_existing_family
        job.skipped_count = result.skipped
        job.failed_rows = [list(item) for item in result.failed]
        job.unhandled_balances = [list(item) for item in result.unhandled_balances]
        job.status = ImportJob.Status.DONE
    except Exception as exc:  # noqa: BLE001 — статус задачи должен отразить любую поломку, не только ожидаемые
        job.status = ImportJob.Status.FAILED
        job.error_message = str(exc)
    finally:
        job.finished_at = timezone.now()
        job.save()
