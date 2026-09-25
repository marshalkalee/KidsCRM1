"""
API импорта детей (/api/v1/clients/children/import/...) — для отдельного
фронтенда (frontend2). Тот же жизненный цикл, что у веб-экранов
(import_jobs.py), никакой своей логики записи:

0. POST analyze/  (multipart: file) — только читает файл: заголовки,
   маппинг (сохранённый для такого набора заголовков или угаданный),
   первые строки и недостающие обязательные поля. Для экрана маппинга —
   ничего не пишет.
1. POST preview/  (multipart: file, mapping? — JSON {поле: колонка}) —
   маппинг из запроса (и тогда он сохраняется для этого набора заголовков)
   или сохранённый/угаданный; ставит в очередь СУХОЙ прогон. Ответ 202
   {job_id} — сам прогон идёт в фоне.
2. GET  jobs/<id>/ — статус и прогресс; для готового сухого прогона —
   отчёт по строкам (ошибки, предупреждения, найденные дубли с вариантами
   решения), для импорта — итоговые счётчики.
3. POST confirm/  {job_id, decisions: {номер строки: create_new|attach|skip}}
   — запускает импорт из сухого прогона. Импорт транзакционный: целиком
   или ничего. Из одного сухого прогона — не больше одного импорта.
   POST jobs/<id>/decisions/ {decisions?, bulk_kind?, bulk_decision?} —
   сохранить решения по строке или массово для вида совпадения.
   GET  jobs/<id>/report.xlsx — отчёт сухого прогона файлом.
4. POST jobs/<id>/rollback/ — откат импорта, пока с данными не работали;
   причины, почему нельзя, — в rollback_blockers ответа jobs/<id>/.
5. GET  jobs/ — последние импорты (история с откатом).
"""

import json

from django.core.exceptions import ValidationError
from django.http import HttpResponse
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
    rollback_blockers,
    rollback_import,
)
from .models import ImportJob
from .reporting import build_report_workbook

PREVIEW_ROW_LIMIT = 5  # сколько строк файла показать на экране маппинга
HISTORY_LIMIT = 10


def _mapping_for(organization, headers):
    saved = import_jobs.saved_mapping(organization, headers)
    return saved.mapping if saved else column_mapping.guess_mapping(headers)


def _missing_required(mapping) -> list[str]:
    return [
        label
        for key, label, required in column_mapping.SYSTEM_FIELDS
        if required and not mapping.get(key)
    ]


def _read_upload(request):
    """(headers, raw_rows, meta) или Response с ошибкой — общая часть
    analyze/ и preview/."""
    uploaded = request.FILES.get("file")
    if not uploaded:
        return Response({"file": ["Файл обязателен."]}, status=status.HTTP_400_BAD_REQUEST)
    try:
        headers, raw_rows, meta = column_mapping.read_uploaded_file(uploaded, uploaded.name)
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
    return headers, raw_rows, meta


def _preview_value(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


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
                "duplicate_kinds": import_jobs.duplicate_kinds(job),
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
                "rollback_blockers": [] if job.rolled_back_at else rollback_blockers(job),
            }
        )
    return data


def _get_job(request, job_id) -> ImportJob | None:
    # job_id — уже UUID (конвертер маршрута <uuid:...>).
    return ImportJob.objects.for_tenant(request.user.organization).filter(pk=job_id).first()


@api_view(["POST"])
@permission_classes([IsOwnerOrManagerOrAdmin])
def import_analyze(request):
    read = _read_upload(request)
    if isinstance(read, Response):
        return read
    headers, raw_rows, _meta = read
    saved = import_jobs.saved_mapping(request.user.organization, headers)
    mapping = saved.mapping if saved else column_mapping.guess_mapping(headers)
    return Response(
        {
            "headers": headers,
            "mapping": mapping,
            "mapping_saved": saved is not None,
            "fields": [
                {"key": key, "label": label, "required": required}
                for key, label, required in column_mapping.SYSTEM_FIELDS
            ],
            "missing_required": _missing_required(mapping),
            "preview_rows": [
                {"row_number": row_number, "values": [_preview_value(v) for v in values]}
                for row_number, values in raw_rows[:PREVIEW_ROW_LIMIT]
            ],
            "total_rows": len(raw_rows),
        }
    )


def _posted_mapping(request, headers):
    """Маппинг из запроса: {поле системы: заголовок колонки}. Неизвестные
    поля и колонки, которых нет в файле, отбрасываются (None), не ошибка."""
    raw = request.data.get("mapping")
    if not raw:
        return None
    try:
        posted = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (TypeError, ValueError):
        return None
    return {
        key: posted.get(key) if posted.get(key) in headers else None
        for key, _, _ in column_mapping.SYSTEM_FIELDS
    }


@api_view(["POST"])
@permission_classes([IsOwnerOrManagerOrAdmin])
def import_preview(request):
    read = _read_upload(request)
    if isinstance(read, Response):
        return read
    headers, raw_rows, meta = read

    organization = request.user.organization
    posted = _posted_mapping(request, headers)
    mapping = posted or _mapping_for(organization, headers)
    missing = _missing_required(mapping)
    if missing:
        field = "mapping" if posted else "file"
        verb = "Не выбраны" if posted else "Не найдены"
        return Response(
            {field: [f"{verb} обязательные колонки: {', '.join(missing)}."]},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if posted:
        # Поправили мышью — запоминаем для этого набора заголовков.
        import_jobs.save_mapping(organization, headers, mapping, meta)

    mapped_rows = column_mapping.apply_mapping(headers, raw_rows, mapping)
    rows = build_rows(mapped_rows, DirectoryLookup.load(organization))
    job = import_jobs.start_dry_run(organization, request.user, rows)
    return Response(_job_payload(job), status=status.HTTP_202_ACCEPTED)


@api_view(["GET"])
@permission_classes([IsOwnerOrManagerOrAdmin])
def import_jobs_list(request):
    """Последние импорты (не сухие прогоны) — история с откатом."""
    jobs = (
        ImportJob.objects.for_tenant(request.user.organization)
        .filter(job_type=ImportJob.JobType.EXECUTE)
        .select_related("created_by")
        .order_by("-created_at")[:HISTORY_LIMIT]
    )
    return Response(
        {
            "results": [
                {
                    "job_id": str(job.id),
                    "status": job.status,
                    "created_at": job.created_at,
                    "created_by": job.created_by.full_name,
                    "total_rows": job.total_rows,
                    "children_created": job.created_count + job.attached_count,
                    "rolled_back_at": job.rolled_back_at,
                }
                for job in jobs
            ]
        }
    )


@api_view(["POST"])
@permission_classes([IsOwnerOrManagerOrAdmin])
def import_decisions(request, job_id):
    decisions = request.data.get("decisions") or {}
    if not isinstance(decisions, dict):
        return Response(
            {"detail": "decisions — {номер строки: решение}."}, status=status.HTTP_400_BAD_REQUEST
        )
    try:
        job = import_jobs.save_decisions(
            request.user.organization,
            job_id,
            per_row=decisions,
            bulk_kind=request.data.get("bulk_kind"),
            bulk_decision=request.data.get("bulk_decision"),
        )
    except ImportJob.DoesNotExist:
        return Response(
            {"detail": "Готовый сухой прогон не найден."}, status=status.HTTP_404_NOT_FOUND
        )
    return Response(_job_payload(job))


@api_view(["GET"])
@permission_classes([IsOwnerOrManagerOrAdmin])
def import_report(request, job_id):
    job = _get_job(request, job_id)
    if (
        job is None
        or job.job_type != ImportJob.JobType.DRY_RUN
        or job.status != ImportJob.Status.DONE
    ):
        return Response(status=status.HTTP_404_NOT_FOUND)
    workbook = build_report_workbook(job.report_rows)
    response = HttpResponse(
        workbook.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="import_report_{job.id}.xlsx"'
    return response


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
