"""
API импорта детей (/api/v1/clients/children/import/...) — для отдельного
фронтенда (frontend2). Тот же жизненный цикл, что у веб-экранов
(import_jobs.py), никакой своей логики записи:

1. POST preview/  (multipart: file) — читает .xlsx/.csv, маппинг колонок
   (сохранённый для такого набора заголовков или угаданный), ставит в
   очередь СУХОЙ прогон. Ответ 202 {job_id} — сам прогон идёт в фоне.
2. GET  jobs/<id>/ — статус и прогресс; для готового сухого прогона —
   отчёт по строкам (ошибки, предупреждения, найденные дубли с вариантами
   решения), для импорта — итоговые счётчики.
3. POST confirm/  {job_id, decisions: {номер строки: create_new|attach|skip}}
   — запускает импорт из сухого прогона. Импорт транзакционный: целиком
   или ничего. Из одного сухого прогона — не больше одного импорта.
4. POST jobs/<id>/rollback/ — откат импорта, пока с данными не работали.
"""

from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from domains.platform.core.permissions import IsOwnerOrManagerOrAdmin

from . import column_mapping, import_jobs, progress
from .import_service import (
    DECISION_LABELS,
    DUPLICATE_KIND_LABELS,
    DirectoryLookup,
    RollbackNotAllowed,
    build_rows,
    rollback_import,
)
from .models import ImportColumnMapping, ImportJob


def _mapping_for(organization, headers):
    saved = (
        ImportColumnMapping.objects.for_tenant(organization)
        .filter(headers_key="|".join(headers))
        .first()
    )
    return saved.mapping if saved else column_mapping.guess_mapping(headers)


def _job_payload(job: ImportJob) -> dict:
    data = {
        "job_id": str(job.id),
        "job_type": job.job_type,
        "status": job.status,
        "total_rows": job.total_rows,
        "error_message": job.error_message,
    }
    if job.status in (ImportJob.Status.PENDING, ImportJob.Status.RUNNING):
        data["progress"] = progress.get_progress(job.id)
    if job.status != ImportJob.Status.DONE:
        return data
    if job.job_type == ImportJob.JobType.DRY_RUN:
        data.update(
            {
                "ready_count": job.ready_count,
                "warning_count": job.warning_count,
                "error_count": job.error_count,
                "executed_job_id": str(job.executed_job_id) if job.executed_job_id else None,
                "decisions": job.decisions,
                "rows": [
                    {
                        **row,
                        "duplicate": (
                            {
                                **row["duplicate"],
                                "kind_label": DUPLICATE_KIND_LABELS[row["duplicate"]["kind"]],
                                "option_labels": DECISION_LABELS[row["duplicate"]["kind"]],
                            }
                            if row.get("duplicate")
                            else None
                        ),
                    }
                    for row in job.report_rows
                ],
            }
        )
    else:
        data.update(
            {
                "children_created": job.created_count + job.attached_count,
                "parents_created": job.parents_created_count,
                "attached_to_existing_parent": job.attached_count,
                "linked_to_existing_child": job.linked_count,
                "enrolled_in_groups": job.enrolled_count,
                "skipped": job.skipped_count,
                "not_imported": job.failed_rows,
                "unhandled_balances": job.unhandled_balances,
                "rolled_back_at": job.rolled_back_at,
            }
        )
    return data


def _get_job(request, job_id) -> ImportJob | None:
    # job_id — уже UUID (конвертер маршрута <uuid:...>).
    return ImportJob.objects.for_tenant(request.user.organization).filter(pk=job_id).first()


@api_view(["POST"])
@permission_classes([IsOwnerOrManagerOrAdmin])
def import_preview(request):
    uploaded = request.FILES.get("file")
    if not uploaded:
        return Response({"file": ["Файл обязателен."]}, status=status.HTTP_400_BAD_REQUEST)
    try:
        headers, raw_rows, _meta = column_mapping.read_uploaded_file(uploaded, uploaded.name)
    except Exception:  # noqa: BLE001 — битый/неожиданный файл — ошибка запроса, не 500
        return Response(
            {"file": ["Не удалось прочитать файл — убедитесь, что это .xlsx или .csv."]},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not headers or not raw_rows:
        return Response(
            {"file": ["В файле не нашлось ни заголовков, ни строк с данными."]},
            status=status.HTTP_400_BAD_REQUEST,
        )

    organization = request.user.organization
    mapping = _mapping_for(organization, headers)
    missing = [
        label
        for key, label, required in column_mapping.SYSTEM_FIELDS
        if required and not mapping.get(key)
    ]
    if missing:
        return Response(
            {"file": [f"Не найдены обязательные колонки: {', '.join(missing)}."]},
            status=status.HTTP_400_BAD_REQUEST,
        )

    mapped_rows = column_mapping.apply_mapping(headers, raw_rows, mapping)
    rows = build_rows(mapped_rows, DirectoryLookup.load(organization))
    job = import_jobs.start_dry_run(organization, request.user, rows)
    return Response(_job_payload(job), status=status.HTTP_202_ACCEPTED)


@api_view(["GET"])
@permission_classes([IsOwnerOrManagerOrAdmin])
def import_job_detail(request, job_id):
    job = _get_job(request, job_id)
    if job is None:
        return Response(status=status.HTTP_404_NOT_FOUND)
    return Response(_job_payload(job))


@api_view(["POST"])
@permission_classes([IsOwnerOrManagerOrAdmin])
def import_confirm(request):
    job_id = request.data.get("job_id")
    decisions = request.data.get("decisions") or {}
    if not job_id or not isinstance(decisions, dict):
        return Response(
            {"detail": "Нужны job_id сухого прогона и decisions — {номер строки: решение}."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        job = import_jobs.start_execute(
            request.user.organization, request.user, job_id, per_row=decisions
        )
    except (ImportJob.DoesNotExist, ValidationError):
        return Response(
            {"detail": "Готовый сухой прогон не найден."}, status=status.HTTP_404_NOT_FOUND
        )
    return Response(_job_payload(job), status=status.HTTP_202_ACCEPTED)


@api_view(["POST"])
@permission_classes([IsOwnerOrManagerOrAdmin])
def import_rollback(request, job_id):
    job = _get_job(request, job_id)
    if job is None or job.job_type != ImportJob.JobType.EXECUTE:
        return Response(status=status.HTTP_404_NOT_FOUND)
    try:
        rollback_import(job, request.user)
    except RollbackNotAllowed as exc:
        return Response({"detail": f"Откат невозможен: {exc}."}, status=status.HTTP_409_CONFLICT)
    job.refresh_from_db()
    return Response(_job_payload(job))
