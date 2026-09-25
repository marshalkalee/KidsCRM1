"""Выгрузка списка задолженностей файлом (ТЗ п. 4.4) — .xlsx, по тому же
паттерну, что и отчёт импорта (domains.people.clients.reporting)."""

import io

import openpyxl
from openpyxl.styles import Font

from .debt import debt_age_days


def build_debtors_workbook(subscriptions) -> io.BytesIO:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Задолженности"
    sheet.append(["Ребёнок", "Родитель", "Абонемент", "Долг", "Давность, дней"])
    for cell in sheet[1]:
        cell.font = Font(bold=True)

    for sub in subscriptions:
        payer = sub.child.contacts.filter(is_payer=True).select_related("parent_contact").first()
        sheet.append(
            [
                sub.child.full_name,
                payer.parent_contact.full_name if payer else "",
                sub.subscription_type_version.name,
                int(sub.price - sub.paid),
                debt_age_days(sub),
            ]
        )

    for column_cells in sheet.columns:
        longest = max(len(str(cell.value or "")) for cell in column_cells)
        sheet.column_dimensions[column_cells[0].column_letter].width = min(longest + 2, 80)

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer
