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
   (`child_import_report_download`).
4. Запуск настоящего импорта из отчёта (`child_import_execute`) — берёт
   строки БЕЗ ошибок из уже посчитанного сухого прогона (не пересобирает
   файл заново) и ставит в очередь `tasks.run_import_job`. Статус — та же
   `child_import_job_status`, но для job_type=EXECUTE.

Сырые строки файла между шагами 1 и 2 передаются одним скрытым JSON-полем
(шаг 1 ничего не пишет в базу — можно просто уйти со страницы маппинга).
Дальше (сухой прогон → выполнение) строки уже лежат в ImportJob.rows_payload
на сервере — второй раз через форму их гонять незачем и рискованно на
тысячах строк.
"""

import datetime
import json

from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from domains.platform.core.decorators import role_required
from domains.platform.tenants.models import Direction

from . import column_mapping
from .forms import ChildImportUploadForm
from .import_service import ImportRow, build_rows
from .models import ImportColumnMapping, ImportJob
from .reporting import build_report_workbook
from .tasks import run_dry_run_job, run_import_job
from .web_views import CHILD_EDIT_ROLES

PREVIEW_ROW_LIMIT = 5  # сколько сырых строк показать на экране маппинга
# Сколько строк отчёта показать на странице (не тысячи — для этого выгрузка файлом).
REPORT_SAMPLE_LIMIT = 200


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


def _known_names(queryset) -> frozenset[str]:
    names = queryset.values_list("name", flat=True)
    return frozenset(name.strip().lower() for name in names if name)


def _known_group_names(organization) -> frozenset[str]:
    # Локальный импорт — clients не держит постоянную зависимость от
    # домена Дарьи (groups) на уровне модуля, только там, где реально
    # нужно свериться со справочником (см. докстринг ImportRow в
    # import_service.py: своей FK на Group этот домен сознательно не
    # заводит).
    from domains.scheduling.groups.models import Group

    return _known_names(Group.objects.for_tenant(organization))


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
    # Один запрос на направления/группы на весь файл, не на строку —
    # 5000 повторов того же SELECT ничего не строке не даёт (ТЗ п. 10.1).
    known_direction_names = _known_names(Direction.objects.for_tenant(org))
    known_group_names = _known_group_names(org)
    rows = build_rows(mapped_rows, known_direction_names, known_group_names)

    job = ImportJob.objects.create(
        organization=org,
        created_by=request.user,
        job_type=ImportJob.JobType.DRY_RUN,
        total_rows=len(rows),
        rows_payload=[r.to_dict() for r in rows],
    )
    run_dry_run_job.delay(str(job.id))
    return redirect("clients_web:child-import-job-status", job_id=job.id)


@role_required(*CHILD_EDIT_ROLES)
def child_import_job_status(request, job_id):
    job = get_object_or_404(ImportJob.objects.for_tenant(request.user.organization), pk=job_id)
    report_rows = job.report_rows[:REPORT_SAMPLE_LIMIT]
    return render(
        request,
        "clients/child_import_job_status.html",
        {
            "job": job,
            "report_rows": report_rows,
            "report_rows_truncated": len(job.report_rows) > REPORT_SAMPLE_LIMIT,
        },
    )


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


@role_required(*CHILD_EDIT_ROLES)
@require_http_methods(["POST"])
def child_import_execute(request, job_id):
    with transaction.atomic():
        # select_for_update — двойной клик по «Запустить импорт» не должен
        # создать две задачи, которые параллельно запишут одних и тех же
        # детей до того, как дедуп одной из них увидит записи другой.
        dry_run_job = get_object_or_404(
            ImportJob.objects.for_tenant(request.user.organization).select_for_update(),
            pk=job_id,
            job_type=ImportJob.JobType.DRY_RUN,
            status=ImportJob.Status.DONE,
        )
        if dry_run_job.executed_job_id:
            return redirect(
                "clients_web:child-import-job-status", job_id=dry_run_job.executed_job_id
            )

        rows = [ImportRow.from_dict(data) for data in dry_run_job.rows_payload]
        ready_rows = [r for r in rows if r.is_valid]  # ошибки блокируют строку — не идут дальше

        job = ImportJob.objects.create(
            organization=request.user.organization,
            created_by=request.user,
            job_type=ImportJob.JobType.EXECUTE,
            total_rows=len(ready_rows),
            rows_payload=[r.to_dict() for r in ready_rows],
        )
        dry_run_job.executed_job = job
        dry_run_job.save(update_fields=["executed_job"])

    run_import_job.delay(str(job.id))
    return redirect("clients_web:child-import-job-status", job_id=job.id)
