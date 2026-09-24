"""
Выгрузка отчёта сухого прогона файлом (ТЗ п. 4.1: «отчёт выгружается
файлом и открывается в Excel») — .xlsx, не .csv: администратор открывает
его сразу после сухого прогона, необязательно гадать с разделителем или
кодировкой ещё раз (ту же грязь этот импорт умеет разбирать на входе).
"""

import io

import openpyxl
from openpyxl.styles import Font

from .import_service import ReportLevel

_LEVEL_LABELS = {
    ReportLevel.READY: "Готово",
    ReportLevel.WARNING: "Предупреждение",
    ReportLevel.ERROR: "Ошибка",
}


def build_report_workbook(report_rows: list[dict]) -> io.BytesIO:
    """report_rows — job.report_rows (см. import_service.build_dry_run_report):
    номер строки — из исходного файла, не внутренний индекс (ТЗ п. 10.4) —
    администратор ищет проблему в том же Excel, откуда грузил файл."""
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Отчёт импорта"
    sheet.append(["Строка", "Статус", "ФИО ребёнка", "Сообщения"])
    for cell in sheet[1]:
        cell.font = Font(bold=True)

    for row in report_rows:
        sheet.append(
            [
                row["row_number"],
                _LEVEL_LABELS.get(row["level"], row["level"]),
                row.get("child_name") or "",
                "; ".join(row.get("messages") or []),
            ]
        )

    for column_cells in sheet.columns:
        longest = max(len(str(cell.value or "")) for cell in column_cells)
        sheet.column_dimensions[column_cells[0].column_letter].width = min(longest + 2, 80)

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer
