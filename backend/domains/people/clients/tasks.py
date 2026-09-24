"""
Импорт файла — фоновая задача (ТЗ п. 10.1), не HTTP-запрос: на файле в
тысячи строк ChildService.find_duplicates() на каждую новую семью не
укладывается в бюджет одного запроса. Строки на момент постановки в
очередь уже распознаны/провалидированы (import_views.py,
ImportRow.to_dict()) — здесь только дедуп (resolve_rows) и, в зависимости
от вида задачи, либо запись (run_import_job/execute_import), либо только
отчёт без единой записи (run_dry_run_job, ТЗ п. 4.1: сухой прогон).
"""

from celery import shared_task
from django.utils import timezone

from .import_service import ImportRow, build_dry_run_report, execute_import, resolve_rows
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


@shared_task
def run_dry_run_job(job_id: str) -> None:
    """Сухой прогон (ТЗ п. 4.1): дедуп (resolve_rows) читает базу, но
    execute_import здесь никогда не вызывается — ни одна строка не
    пишется ни в Child, ни в ParentContact. Пишем только в саму запись
    ImportJob (статус, отчёт) — это учёт задачи, не бизнес-данные."""
    job = ImportJob.objects.get(pk=job_id)
    job.status = ImportJob.Status.RUNNING
    job.save(update_fields=["status"])

    try:
        rows = [ImportRow.from_dict(data) for data in job.rows_payload]
        resolve_rows(job.organization, rows)
        report = build_dry_run_report(rows)

        job.ready_count = report.ready_count
        job.warning_count = report.warning_count
        job.error_count = report.error_count
        job.report_rows = report.rows
        job.status = ImportJob.Status.DONE
    except Exception as exc:  # noqa: BLE001 — статус задачи должен отразить любую поломку, не только ожидаемые
        job.status = ImportJob.Status.FAILED
        job.error_message = str(exc)
    finally:
        job.finished_at = timezone.now()
        job.save()
