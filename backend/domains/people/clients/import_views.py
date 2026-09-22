"""
Веб-экраны импорта детей (ТЗ п. 4.1: загрузка .xlsx/.csv, маппинг
колонок; п. 10.1: фоновая задача через очередь). Три шага:

1. Загрузка (`child_import_upload`) — читает файл как есть (без
   фиксированных колонок), угадывает маппинг, показывает экран маппинга.
2. Подтверждение маппинга (`child_import_mapping_confirm`) — применяет
   выбранный маппинг, чистит/валидирует значения (import_service.build_rows),
   сохраняет маппинг на будущее (повторный импорт того же файла не требует
   настраивать заново), показывает сводку "распознано/не распознано".
3. Запуск (`child_import_start`) — создаёт ImportJob и ставит в очередь
   (tasks.run_import_job) — дедуп и создание записей происходят в фоне, не
   в этом запросе (файл на тысячи строк не должен ронять запрос по
   таймауту). Статус — `child_import_job_status`.

Сырые строки файла между шагами 1 и 2 передаются одним скрытым JSON-полем
(шаг 1 ничего не пишет в базу — можно просто уйти со страницы маппинга).
Между шагом 2 и 3 — так же, уже очищенными/провалидированными строками.
"""

import datetime
import json

from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from domains.platform.core.decorators import role_required

from . import column_mapping
from .forms import ChildImportUploadForm
from .import_service import ImportRow, build_rows
from .models import ImportColumnMapping, ImportJob
from .tasks import run_import_job
from .web_views import CHILD_EDIT_ROLES

PREVIEW_ROW_LIMIT = 5  # сколько сырых строк показать на экране маппинга
SUMMARY_SAMPLE_LIMIT = 20  # сколько распознанных строк показать в сводке
SUMMARY_ERROR_LIMIT = 100  # сколько строк с ошибками показать (не тысячи)


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

    _save_mapping(request.user.organization, headers, mapping, meta)

    mapped_rows = column_mapping.apply_mapping(
        headers, [(rn, values) for rn, values in raw_rows], mapping
    )
    rows = build_rows(mapped_rows)
    valid_rows = [r for r in rows if r.is_valid]
    error_rows = [r for r in rows if not r.is_valid]

    return render(
        request,
        "clients/child_import_summary.html",
        {
            "total_rows": len(rows),
            "valid_count": len(valid_rows),
            "error_count": len(error_rows),
            "sample_rows": valid_rows[:SUMMARY_SAMPLE_LIMIT],
            "error_rows": error_rows[:SUMMARY_ERROR_LIMIT],
            "error_rows_truncated": len(error_rows) > SUMMARY_ERROR_LIMIT,
            "valid_rows_json": json.dumps([r.to_dict() for r in valid_rows]),
        },
    )


@role_required(*CHILD_EDIT_ROLES)
@require_http_methods(["POST"])
def child_import_start(request):
    try:
        raw_valid_rows = json.loads(request.POST.get("valid_rows_json", "[]"))
    except json.JSONDecodeError:
        return redirect(reverse("clients_web:child-import-upload"))

    rows = [ImportRow.from_dict(data) for data in raw_valid_rows]
    job = ImportJob.objects.create(
        organization=request.user.organization,
        created_by=request.user,
        total_rows=len(rows),
        rows_payload=[r.to_dict() for r in rows],
    )
    run_import_job.delay(str(job.id))
    return redirect("clients_web:child-import-job-status", job_id=job.id)


@role_required(*CHILD_EDIT_ROLES)
def child_import_job_status(request, job_id):
    job = get_object_or_404(ImportJob.objects.for_tenant(request.user.organization), pk=job_id)
    return render(request, "clients/child_import_job_status.html", {"job": job})
