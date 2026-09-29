"""Выгрузка списка задолженностей файлом (ТЗ п. 4.4) — .xlsx, по тому же
паттерну, что и отчёт импорта (domains.people.clients.reporting). Строки —
те же, что на экране (lists_api.debtor_rows): файл и экран не расходятся."""

import io

import openpyxl
from openpyxl.styles import Font


def build_debtors_workbook(rows, *, show_phones=False) -> io.BytesIO:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Задолженности"
    header = ["Ребёнок", "Плательщик"]
    if show_phones:
        header.append("Телефон")
    header += ["Абонемент", "Направление", "Филиал", "Цена", "Оплачено", "Долг", "Давность, дней"]
    sheet.append(header)
    for cell in sheet[1]:
        cell.font = Font(bold=True)

    for row in rows:
        values = [row["child_name"], row["parent_name"]]
        if show_phones:
            values.append(row["phone"] or "")
        values += [
            row["subscription_name"],
            row["direction_name"],
            row["branch_name"],
            int(float(row["price"])),
            int(float(row["paid"])),
            int(float(row["debt"])),
            row["age_days"],
        ]
        sheet.append(values)

    total_row = sheet.max_row + 1
    debt_column = header.index("Долг") + 1
    sheet.cell(row=total_row, column=1, value="Итого").font = Font(bold=True)
    total_debt = sum(int(float(r["debt"])) for r in rows)
    sheet.cell(row=total_row, column=debt_column, value=total_debt).font = Font(bold=True)

    for column_cells in sheet.columns:
        longest = max(len(str(cell.value or "")) for cell in column_cells)
        sheet.column_dimensions[column_cells[0].column_letter].width = min(longest + 2, 60)

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer
