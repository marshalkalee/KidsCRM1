"""
Жизненный цикл импорта — общий для веб-экранов (import_views.py) и API
(import_api_views.py): сухой прогон → решения по дублям → запуск импорта.
Один путь, чтобы веб и API не разошлись в правилах (один сухой прогон —
не больше одного импорта, решения валидируются по виду совпадения и т.п.).

Функции не знают про HTTP: «не найдено» — ImportJob.DoesNotExist, вьюхи
сами превращают его в 404.
"""

from django.db import transaction

from .import_service import DECISION_OPTIONS, ImportRow
from .models import ImportJob
from .tasks import run_dry_run_job, run_import_job


def start_dry_run(organization, user, rows: list[ImportRow]) -> ImportJob:
    """Строки уже разобраны и провалидированы (build_rows) — ставим сухой
    прогон в очередь: дедуп на тысячах строк не укладывается в запрос."""
    job = ImportJob.objects.create(
        organization=organization,
        created_by=user,
        job_type=ImportJob.JobType.DRY_RUN,
        total_rows=len(rows),
        rows_payload=[row.to_dict() for row in rows],
    )
    run_dry_run_job.delay(str(job.id))
    return job


def duplicate_rows(job: ImportJob) -> list[dict]:
    return [row for row in job.report_rows if row.get("duplicate")]


def merge_decisions(job: ImportJob, per_row=None, bulk_kind=None, bulk_decision=None) -> dict:
    """Новые решения поверх уже сохранённых: по строке ({номер: решение})
    или массово для вида совпадения (bulk_kind + bulk_decision). Решение,
    неприменимое к виду совпадения строки, — игнорируется."""
    per_row = {str(key): value for key, value in (per_row or {}).items()}
    decisions = dict(job.decisions or {})
    for row in duplicate_rows(job):
        key = str(row["row_number"])
        kind = row["duplicate"]["kind"]
        if bulk_kind:
            if kind == bulk_kind and bulk_decision in DECISION_OPTIONS[kind]:
                decisions[key] = bulk_decision
            continue
        value = per_row.get(key)
        if value in DECISION_OPTIONS[kind]:
            decisions[key] = value
    return decisions


def _locked_dry_run(organization, job_id) -> ImportJob:
    # select_for_update — двойной клик / повторный запрос не должен создать
    # две задачи, которые параллельно запишут одних и тех же детей.
    return (
        ImportJob.objects.for_tenant(organization)
        .select_for_update()
        .get(pk=job_id, job_type=ImportJob.JobType.DRY_RUN, status=ImportJob.Status.DONE)
    )


def save_decisions(organization, job_id, per_row=None, bulk_kind=None, bulk_decision=None):
    """Возвращает сухой прогон. Если импорт из него уже запущен — решения не
    меняются (job.executed_job_id заполнен, вызывающий решает, куда вести)."""
    with transaction.atomic():
        job = _locked_dry_run(organization, job_id)
        if not job.executed_job_id:
            job.decisions = merge_decisions(job, per_row, bulk_kind, bulk_decision)
            job.save(update_fields=["decisions"])
    return job


def start_execute(organization, user, dry_run_job_id, per_row=None) -> ImportJob:
    """Импорт из сухого прогона: строки без ошибок + решения по дублям.
    Из одного сухого прогона — не больше одного импорта: повторный вызов
    возвращает уже запущенный."""
    with transaction.atomic():
        dry_run_job = _locked_dry_run(organization, dry_run_job_id)
        if dry_run_job.executed_job_id:
            return dry_run_job.executed_job
        dry_run_job.decisions = merge_decisions(dry_run_job, per_row)

        rows = [ImportRow.from_dict(data) for data in dry_run_job.rows_payload]
        ready_rows = [r for r in rows if r.is_valid]  # ошибки блокируют строку — не идут дальше
        for row in ready_rows:
            row.decision = dry_run_job.decisions.get(str(row.row_number))

        job = ImportJob.objects.create(
            organization=organization,
            created_by=user,
            job_type=ImportJob.JobType.EXECUTE,
            total_rows=len(ready_rows),
            rows_payload=[r.to_dict() for r in ready_rows],
        )
        dry_run_job.executed_job = job
        dry_run_job.save(update_fields=["executed_job", "decisions"])

    run_import_job.delay(str(job.id))
    return job
