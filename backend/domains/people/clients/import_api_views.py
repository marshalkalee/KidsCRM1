from datetime import date

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from domains.platform.core.permissions import IsOwnerOrManagerOrAdmin

from .import_service import ImportRow, RowAction, execute_import, parse_workbook, resolve_rows

ALLOWED_ACTIONS = {RowAction.CREATE_NEW_FAMILY, RowAction.ATTACH_EXISTING, RowAction.SKIP}


def _row_to_dict(row):
    return {
        "row_number": row.row_number,
        "child_name": row.child_name,
        "birth_date": row.birth_date.isoformat() if row.birth_date else None,
        "gender": row.gender,
        "gender_label": "М" if row.gender == "male" else "Ж",
        "parent_name": row.parent_name,
        "phone": row.phone,
        "role": row.role,
        "role_label": row.role or "—",
        "action": row.action,
        "matched_parent_id": str(row.matched_parent_id) if row.matched_parent_id else None,
        "reason": getattr(row, "reason", None),
    }


def _row_from_dict(data, action):
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


@api_view(["POST"])
@permission_classes([IsOwnerOrManagerOrAdmin])
def import_preview(request):
    file = request.FILES.get("file")
    if not file:
        return Response({"file": ["Файл обязателен."]}, status=status.HTTP_400_BAD_REQUEST)
    try:
        rows, header_errors = parse_workbook(file)
    except Exception:
        return Response(
            {"file": ["Не удалось прочитать файл — убедитесь, что это .xlsx."]},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if header_errors:
        return Response({"file": header_errors}, status=status.HTTP_400_BAD_REQUEST)

    resolve_rows(request.user.organization, rows)

    return Response(
        {
            "rows": [_row_to_dict(r) for r in rows if r.is_valid],
            "error_rows": [
                {
                    "row_number": r.row_number,
                    "child_name": r.child_name,
                    "errors": r.errors,
                }
                for r in rows
                if not r.is_valid
            ],
        }
    )


@api_view(["POST"])
@permission_classes([IsOwnerOrManagerOrAdmin])
def import_confirm(request):
    raw_rows = request.data.get("rows", [])
    if not raw_rows:
        return Response({"detail": "Нет строк для импорта."}, status=status.HTTP_400_BAD_REQUEST)

    rows = []
    for data in raw_rows:
        action = data.get("action", RowAction.SKIP)
        if action not in ALLOWED_ACTIONS:
            action = RowAction.SKIP
        rows.append(_row_from_dict(data, action))

    result = execute_import(request.user.organization, rows)
    return Response(
        {
            "created": result.created,
            "attached_to_existing_family": result.attached_to_existing_family,
            "skipped": result.skipped,
            "failed": result.failed,
        }
    )
