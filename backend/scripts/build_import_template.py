#!/usr/bin/env python
"""
Собирает шаблон Excel для импорта детей (static/site/files/
child_import_template.xlsx) — лист-инструкция + лист с примером
заполнения. Запуск: python backend/scripts/build_import_template.py.

Колонки должны совпадать по смыслу с SYSTEM_FIELDS в
domains/people/clients/column_mapping.py (не обязаны совпадать по
названию — см. маппинг колонок) — при изменении формата обновить оба
места (и docs/import_format.md).
"""

from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent
    / "static"
    / "site"
    / "files"
    / "child_import_template.xlsx"
)

INSTRUCTIONS = [
    ("Колонка", "Обязательна?", "Формат", "Пример"),
    ("ФИО ребёнка", "Да", "Текст", "Серикова Айгерим"),
    (
        "Дата рождения ребёнка",
        "Да",
        "ДД.ММ.ГГГГ (также понимает ДД/ММ/ГГГГ и ГГГГ-ММ-ДД)",
        "10.03.2018",
    ),
    ("Пол ребёнка", "Да", "М или Ж (также «мужской»/«женский»)", "Ж"),
    (
        "ФИО родителя",
        "Да",
        "Текст. Можно с ролью впереди («мама Иванова Марина») — роль распознается автоматически",
        "Иванова Марина",
    ),
    (
        "Телефон родителя",
        "Да",
        "Казахстанский номер. Несколько номеров через запятую — сохранятся все",
        "+7 701 123 45 67",
    ),
    (
        "Роль родителя",
        "Нет",
        "мама / папа / опекун / бабушка / другое. Если пусто — берётся из ФИО родителя "
        "или «другое»",
        "мама",
    ),
    (
        "Медицинские заметки",
        "Нет",
        "Текст — переносится в карточку ребёнка как есть",
        "Аллергия на цитрусы",
    ),
    (
        "Остаток занятий",
        "Нет",
        "Число. НЕ создаёт абонемент автоматически — только показывается в отчёте после импорта "
        "для переноса вручную (см. документацию формата)",
        "5",
    ),
    (
        "Направление",
        "Нет",
        "Текст. НЕ создаётся автоматически — сухой прогон предупредит, если такого направления "
        "ещё нет в справочнике",
        "Балет",
    ),
    (
        "Группа",
        "Нет",
        "Текст. НЕ создаётся автоматически — сухой прогон предупредит, если такой группы ещё нет",
        "Балет-мини вторник/четверг",
    ),
]

DATA_HEADERS = [
    "ФИО ребёнка",
    "Дата рождения ребёнка",
    "Пол ребёнка",
    "ФИО родителя",
    "Телефон родителя",
    "Роль родителя",
    "Медицинские заметки",
    "Остаток занятий",
    "Направление",
    "Группа",
]

EXAMPLE_ROWS = [
    [
        "Серикова Айгерим",
        "10.03.2018",
        "Ж",
        "Иванова Марина",
        "+7 701 123 45 67",
        "мама",
        "",
        "",
        "Балет",
        "Балет-мини вторник/четверг",
    ],
    [
        "Серикова Данияр",
        "05.07.2020",
        "М",
        "Иванова Марина",
        "+7 701 123 45 67",
        "папа",
        "Аллергия на орехи",
        "",
        "",
        "",
    ],
]


def _autosize(sheet, widths):
    for idx, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(idx)].width = width


def build():
    wb = openpyxl.Workbook()

    instructions = wb.active
    instructions.title = "Инструкция"
    instructions.append(
        ["Импорт детей — формат файла. Заполните лист «Дети» по образцу и удалите пример."]
    )
    instructions["A1"].font = Font(bold=True, size=13)
    instructions.append([])
    header_row_idx = instructions.max_row + 1
    for row in INSTRUCTIONS:
        instructions.append(row)
    for col in range(1, 5):
        cell = instructions.cell(row=header_row_idx, column=col)
        cell.font = Font(bold=True)
    for row in instructions.iter_rows(min_row=header_row_idx + 1):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    _autosize(instructions, [22, 14, 46, 26])

    data = wb.create_sheet("Дети")
    data.append(DATA_HEADERS)
    for col in range(1, len(DATA_HEADERS) + 1):
        data.cell(row=1, column=col).font = Font(bold=True)
    for row in EXAMPLE_ROWS:
        data.append(row)
    _autosize(data, [22, 20, 12, 20, 20, 16, 26, 16, 16, 26])

    wb.active = wb.sheetnames.index("Дети")
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUTPUT_PATH)
    print(f"Шаблон сохранён: {OUTPUT_PATH}")


if __name__ == "__main__":
    build()
