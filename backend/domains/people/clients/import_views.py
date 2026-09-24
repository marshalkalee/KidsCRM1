"""
Веб-экраны импорта детей (ТЗ п. 4.1: загрузка .xlsx/.csv, маппинг колонок,
сухой прогон и отчёт об ошибках; п. 10.1: фоновая задача через очередь).
Шаги:

1. Загрузка (`child_import_upload`) — читает файл как есть (без
   фиксированных колонок), угадывает маппинг, показывает экран маппинга.
2. Подтверждение маппинга (`child_import_mapping_confirm`) — применяет
   выбранный маппинг, чистит/валидирует значения (import_service.build_rows),
   сохраняет маппинг на будущее (повторный импорт того же файла не требует
   настраивать заново), сразу ставит в очередь СУХОЙ прогон
   (tasks.run_dry_run_job) — дедуп на файле в тысячи строк не укладывается
   в бюджет одного запроса, тот же принцип, что и у самого импорта.
3. Статус/отчёт сухого прогона (`child_import_job_status`) — готово/
   предупреждения/ошибки по каждой строке (номер — из исходного файла, не
   внутренний индекс), отчёт можно скачать файлом
   (`child_import_report_download`). Там же — решения по найденным
   совпадениям: по строке или сразу для всех однотипных
   (`child_import_decisions`).
4. Запуск настоящего импорта из отчёта (`child_import_execute`) — берёт
   строки БЕЗ ошибок из уже посчитанного сухого прогона (не пересобирает
   файл заново) вместе с решениями по дублям и ставит в очередь
   `tasks.run_import_job`. Статус (с прогрессом) — та же
   `child_import_job_status`, но для job_type=EXECUTE.
5. Откат импорта целиком (`child_import_rollback`), пока с
   импортированными данными никто не начал работать.

Сырые строки файла между шагами 1 и 2 передаются одним скрытым JSON-полем
(шаг 1 ничего не пишет в базу — можно просто уйти со страницы маппинга).
Дальше (сухой прогон → выполнение) строки уже лежат в ImportJob.rows_payload
на сервере — второй раз через форму их гонять незачем и рискованно на
тысячах строк.
"""

import datetime
import json

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from domains.platform.core.decorators import role_required

from . import column_mapping, import_jobs, progress
from .forms import ChildImportUploadForm
from .import_service import (
    DECISION_LABELS,
    DECISION_OPTIONS,
    DUPLICATE_KIND_LABELS,
    DirectoryLookup,
    RollbackNotAllowed,
    build_rows,
    rollback_blockers,
    rollback_import,
)
from .models import ImportColumnMapping, ImportJob
from .reporting import build_report_workbook
from .web_views import CHILD_EDIT_ROLES

PREVIEW_ROW_LIMIT = 5  # сколько сырых строк показать на экране маппинга
# Сколько строк отчёта показать на странице (не тысячи — для этого выгрузка файлом).
REPORT_SAMPLE_LIMIT = 200
# Сколько совпадений показать для решения по одному — остальные решаются
# массово («для всех однотипных») или остаются с действием по умолчанию.
DUPLICATE_ROW_LIMIT = 500


def _json_safe(value):
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    return value


def _json_safe_rows(raw_rows):
    return [[row_number, [_json_safe(v) for v in values]] for row_number, values in raw_rows]


def _find_saved_mapping(organization, headers):
    headers_key = "|".join(headers)
    return (
        ImportColumnMapping.objects.for_tenant(organization).filter(headers_key=headers_key).first()
    )


def _mapping_rows(mapping):
    """(ключ, подпись, обязательно, текущая_колонка) — шаблон не умеет
    делать mapping[key] по переменному ключу, поэтому подстановка здесь."""
    return [
        (key, label, required, mapping.get(key))
        for key, label, required in column_mapping.SYSTEM_FIELDS
    ]


def _save_mapping(organization, headers, mapping, meta):
    headers_key = "|".join(headers)
    ImportColumnMapping.objects.for_tenant(organization).filter(headers_key=headers_key).delete()
    ImportColumnMapping.objects.create(
        organization=organization,
        headers_key=headers_key,
        file_headers=headers,
        mapping=mapping,
        csv_delimiter=meta.get("delimiter", ""),
        csv_encoding=meta.get("encoding", ""),
    )


@role_required(*CHILD_EDIT_ROLES)
@require_http_methods(["GET", "POST"])
def child_import_upload(request):
    if request.method == "POST":
        form = ChildImportUploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded = form.cleaned_data["file"]
            try:
                headers, raw_rows, meta = column_mapping.read_uploaded_file(uploaded, uploaded.name)
            except Exception:  # noqa: BLE001 — битый/неожиданный файл — форма-ошибка, не 500
                form.add_error(
                    None, "Не удалось прочитать файл — убедитесь, что это .xlsx или .csv."
                )
            else:
                if not headers or not raw_rows:
                    form.add_error(None, "В файле не нашлось ни заголовков, ни строк с данными.")
                else:
                    saved = _find_saved_mapping(request.user.organization, headers)
                    mapping = saved.mapping if saved else column_mapping.guess_mapping(headers)
                    return render(
                        request,
                        "clients/child_import_mapping.html",
                        {
                            "headers": headers,
                            "mapping_rows": _mapping_rows(mapping),
                            "preview_rows": raw_rows[:PREVIEW_ROW_LIMIT],
                            "total_rows": len(raw_rows),
                            "meta": meta,
                            "headers_json": json.dumps(headers),
                            "raw_rows_json": json.dumps(_json_safe_rows(raw_rows)),
                            "meta_json": json.dumps(meta),
                        },
                    )
    else:
        form = ChildImportUploadForm()
    return render(request, "clients/child_import_upload.html", {"form": form})


@role_required(*CHILD_EDIT_ROLES)
@require_http_methods(["POST"])
def child_import_mapping_confirm(request):
    try:
        headers = json.loads(request.POST.get("headers_json", "[]"))
        raw_rows = json.loads(request.POST.get("raw_rows_json", "[]"))
        meta = json.loads(request.POST.get("meta_json", "{}"))
    except json.JSONDecodeError:
        return redirect(reverse("clients_web:child-import-upload"))

    mapping = {
        field_key: request.POST.get(f"mapping_{field_key}") or None
        for field_key, _, _ in column_mapping.SYSTEM_FIELDS
    }
    missing_required = [
        label
        for key, label, required in column_mapping.SYSTEM_FIELDS
        if required and not mapping.get(key)
    ]
    if missing_required:
        return render(
            request,
            "clients/child_import_mapping.html",
            {
                "headers": headers,
                "mapping_rows": _mapping_rows(mapping),
                "preview_rows": raw_rows[:PREVIEW_ROW_LIMIT],
                "total_rows": len(raw_rows),
                "meta": meta,
                "headers_json": json.dumps(headers),
                "raw_rows_json": json.dumps(raw_rows),
                "meta_json": json.dumps(meta),
                "missing_required": missing_required,
            },
        )

    org = request.user.organization
    _save_mapping(org, headers, mapping, meta)

    mapped_rows = column_mapping.apply_mapping(
        headers, [(rn, values) for rn, values in raw_rows], mapping
    )
    # Один запрос на направления/группы на весь файл, не на строку (ТЗ п. 10.1).
    rows = build_rows(mapped_rows, DirectoryLookup.load(org))

    job = import_jobs.start_dry_run(org, request.user, rows)
    return redirect("clients_web:child-import-job-status", job_id=job.id)


def _decision_context(job: ImportJob) -> dict:
    """Экран решений по дублям: по строке (до DUPLICATE_ROW_LIMIT) и сводка
    по видам совпадений для массового решения."""
    duplicate_rows = import_jobs.duplicate_rows(job)
    rows = []
    for row in duplicate_rows[:DUPLICATE_ROW_LIMIT]:
        kind = row["duplicate"]["kind"]
        current = job.decisions.get(str(row["row_number"])) or DECISION_OPTIONS[kind][0]
        rows.append(
            {
                "row_number": row["row_number"],
                "child_name": row["child_name"],
                "kind_label": DUPLICATE_KIND_LABELS[kind],
                "matched": row["duplicate"]["matched"],
                "choices": [
                    (value, DECISION_LABELS[kind][value], value == current)
                    for value in DECISION_OPTIONS[kind]
                ],
            }
        )
    kinds = []
    for kind, label in DUPLICATE_KIND_LABELS.items():
        count = sum(1 for row in duplicate_rows if row["duplicate"]["kind"] == kind)
        if count:
            kinds.append(
                {
                    "kind": kind,
                    "label": label,
                    "count": count,
                    "choices": [
                        (value, DECISION_LABELS[kind][value]) for value in DECISION_OPTIONS[kind]
                    ],
                }
            )
    return {
        "duplicate_rows": rows,
        "duplicate_rows_truncated": len(duplicate_rows) > DUPLICATE_ROW_LIMIT,
        "duplicate_kinds": kinds,
    }


@role_required(*CHILD_EDIT_ROLES)
def child_import_job_status(request, job_id):
    job = get_object_or_404(ImportJob.objects.for_tenant(request.user.organization), pk=job_id)
    context = {
        "job": job,
        "report_rows": job.report_rows[:REPORT_SAMPLE_LIMIT],
        "report_rows_truncated": len(job.report_rows) > REPORT_SAMPLE_LIMIT,
    }
    if job.status in (ImportJob.Status.PENDING, ImportJob.Status.RUNNING):
        context["progress"] = progress.get_progress(job.id)
    if job.job_type == ImportJob.JobType.DRY_RUN and job.status == ImportJob.Status.DONE:
        context.update(_decision_context(job))
    if job.job_type == ImportJob.JobType.EXECUTE and job.status == ImportJob.Status.DONE:
        context["rollback_blockers"] = [] if job.rolled_back_at else rollback_blockers(job)
    return render(request, "clients/child_import_job_status.html", context)


@role_required(*CHILD_EDIT_ROLES)
def child_import_report_download(request, job_id):
    job = get_object_or_404(
        ImportJob.objects.for_tenant(request.user.organization),
        pk=job_id,
        job_type=ImportJob.JobType.DRY_RUN,
        status=ImportJob.Status.DONE,
    )
    workbook = build_report_workbook(job.report_rows)
    response = HttpResponse(
        workbook.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="import_report_{job.id}.xlsx"'
    return response


def _posted_decisions(request) -> dict:
    """{номер строки: решение} из выпадающих списков формы (decision_<номер>)."""
    return {
        key.removeprefix("decision_"): value
        for key, value in request.POST.items()
        if key.startswith("decision_")
    }


@role_required(*CHILD_EDIT_ROLES)
@require_http_methods(["POST"])
def child_import_decisions(request, job_id):
    try:
        job = import_jobs.save_decisions(
            request.user.organization,
            job_id,
            per_row=_posted_decisions(request),
            bulk_kind=request.POST.get("bulk_kind"),
            bulk_decision=request.POST.get("bulk_decision"),
        )
    except ImportJob.DoesNotExist as exc:
        raise Http404 from exc
    if job.executed_job_id:
        return redirect("clients_web:child-import-job-status", job_id=job.executed_job_id)
    messages.success(request, "Решения по совпадениям сохранены.")
    return redirect(reverse("clients_web:child-import-job-status", args=[job.id]) + "#duplicates")


@role_required(*CHILD_EDIT_ROLES)
@require_http_methods(["POST"])
def child_import_execute(request, job_id):
    # Кнопка запуска — в той же форме, что и решения по строкам: выбор в
    # выпадающих списках, который не сохранили отдельно, не теряется.
    try:
        job = import_jobs.start_execute(
            request.user.organization, request.user, job_id, per_row=_posted_decisions(request)
        )
    except ImportJob.DoesNotExist as exc:
        raise Http404 from exc
    return redirect("clients_web:child-import-job-status", job_id=job.id)


@role_required(*CHILD_EDIT_ROLES)
@require_http_methods(["POST"])
def child_import_rollback(request, job_id):
    job = get_object_or_404(
        ImportJob.objects.for_tenant(request.user.organization),
        pk=job_id,
        job_type=ImportJob.JobType.EXECUTE,
    )
    try:
        rollback_import(job, request.user)
    except RollbackNotAllowed as exc:
        messages.error(request, f"Откат невозможен: {exc}.")
    else:
        messages.success(request, "Импорт откатан — созданные им записи удалены.")
    return redirect("clients_web:child-import-job-status", job_id=job.id)
