"""
Веб-экран импорта детей из Excel (ТЗ п. 4.1, MVP критерий приёмки №1) —
загрузка файла, предпросмотр с найденными дублями/"вторыми детьми в
семье", подтверждение. Вся логика дедупа и создания записей —
import_service.py/services.py (ChildService, TRU-8 контракт №2), здесь
только HTTP-обвязка: форма загрузки, передача разобранных строк между
предпросмотром и подтверждением, рендер результата.

Строки между предпросмотром и подтверждением передаются одним скрытым
JSON-полем (не сессией/БД-черновиком) — предпросмотр ничего не пишет в
базу, поэтому «отмена» — это просто не отправить форму подтверждения.
"""

import json
from datetime import date

from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from domains.platform.core.decorators import role_required

from .forms import ChildImportUploadForm
from .import_service import ImportRow, RowAction, execute_import, parse_workbook, resolve_rows
from .web_views import CHILD_EDIT_ROLES

ALLOWED_CONFIRM_ACTIONS = {RowAction.CREATE_NEW_FAMILY, RowAction.ATTACH_EXISTING, RowAction.SKIP}


def _row_to_json(row):
    return {
        "row_number": row.row_number,
        "child_name": row.child_name,
        "birth_date": row.birth_date.isoformat() if row.birth_date else None,
        "gender": row.gender,
        "parent_name": row.parent_name,
        "phone": row.phone,
        "role": row.role,
        "action": row.action,
        "matched_parent_id": row.matched_parent_id,
    }


def _row_from_json(data, action):
    return ImportRow(
        row_number=data["row_number"],
        child_name=data["child_name"],
        birth_date=date.fromisoformat(data["birth_date"]) if data["birth_date"] else None,
        gender=data["gender"],
        parent_name=data["parent_name"],
        phone=data["phone"],
        role=data["role"],
        action=action,
        matched_parent_id=data["matched_parent_id"],
    )


@role_required(*CHILD_EDIT_ROLES)
@require_http_methods(["GET", "POST"])
def child_import_upload(request):
    if request.method == "POST":
        form = ChildImportUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                rows, header_errors = parse_workbook(form.cleaned_data["file"])
            except Exception:  # noqa: BLE001 — битый/не-Excel файл — форма-ошибка, не 500
                header_errors = ["Не удалось прочитать файл — убедитесь, что это .xlsx."]
                rows = []
            if header_errors:
                for error in header_errors:
                    form.add_error(None, error)
            else:
                resolve_rows(request.user.organization, rows)
                valid_rows = [r for r in rows if r.is_valid]
                error_rows = [r for r in rows if not r.is_valid]
                return render(
                    request,
                    "clients/child_import_preview.html",
                    {
                        "rows": valid_rows,
                        "error_rows": error_rows,
                        "rows_json": json.dumps([_row_to_json(r) for r in valid_rows]),
                    },
                )
    else:
        form = ChildImportUploadForm()
    return render(request, "clients/child_import_upload.html", {"form": form})


@role_required(*CHILD_EDIT_ROLES)
@require_http_methods(["POST"])
def child_import_confirm(request):
    try:
        raw_rows = json.loads(request.POST.get("rows_json", "[]"))
    except json.JSONDecodeError:
        return redirect(reverse("clients_web:child-import-upload"))

    rows = []
    for data in raw_rows:
        action = request.POST.get(f"action_{data['row_number']}", data["action"])
        if action not in ALLOWED_CONFIRM_ACTIONS:
            action = data["action"]
        rows.append(_row_from_json(data, action))

    result = execute_import(request.user.organization, rows)
    return render(request, "clients/child_import_result.html", {"result": result})
