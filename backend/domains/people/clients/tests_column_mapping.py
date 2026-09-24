"""
column_mapping.py — чтение .xlsx/.csv и автоугадывание маппинга колонок
(ТЗ п. 4.1). Разбор "грязных" значений ОДНОГО поля — не здесь, см.
tests_import_service.py (build_row); эти тесты — только про то, откуда
берётся сырое значение для каждого поля.
"""

import io

import openpyxl
from django.test import SimpleTestCase

from . import column_mapping

HEADERS = [
    "ФИО ребёнка",
    "Дата рождения ребёнка",
    "Пол ребёнка",
    "ФИО родителя",
    "Телефон родителя",
    "Роль родителя",
]


def _xlsx_bytes(rows, headers=HEADERS, merges=()):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    for merge_range in merges:
        ws.merge_cells(merge_range)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


class GuessMappingTests(SimpleTestCase):
    def test_exact_alias_match(self):
        mapping = column_mapping.guess_mapping(HEADERS)

        self.assertEqual(mapping["child_name"], "ФИО ребёнка")
        self.assertEqual(mapping["birth_date"], "Дата рождения ребёнка")
        self.assertEqual(mapping["gender"], "Пол ребёнка")
        self.assertEqual(mapping["parent_name"], "ФИО родителя")
        self.assertEqual(mapping["phone"], "Телефон родителя")
        self.assertEqual(mapping["role"], "Роль родителя")

    def test_direction_and_group_columns_are_recognized(self):
        mapping = column_mapping.guess_mapping(["Направление", "Группа"])

        self.assertEqual(mapping["direction"], "Направление")
        self.assertEqual(mapping["group"], "Группа")

    def test_direction_and_group_are_optional_fields(self):
        required_keys = {key for key, _, required in column_mapping.SYSTEM_FIELDS if required}

        self.assertNotIn("direction", required_keys)
        self.assertNotIn("group", required_keys)

    def test_unrecognized_header_is_left_unmapped(self):
        mapping = column_mapping.guess_mapping(["Совершенно левая колонка"])

        self.assertTrue(all(v is None for v in mapping.values()))

    def test_missing_column_leaves_field_unmapped(self):
        headers = [h for h in HEADERS if h != "Телефон родителя"]

        mapping = column_mapping.guess_mapping(headers)

        self.assertIsNone(mapping["phone"])
        self.assertEqual(mapping["child_name"], "ФИО ребёнка")

    def test_partial_substring_match_used_as_fallback(self):
        # "Контактный телефон родителя ребёнка" не совпадает ни с одним
        # алиасом ТОЧНО, но содержит алиас "телефон" как подстроку.
        mapping = column_mapping.guess_mapping(["Контактный телефон родителя ребёнка"])

        self.assertEqual(mapping["phone"], "Контактный телефон родителя ребёнка")

    def test_same_header_is_never_assigned_to_two_fields(self):
        # "Родитель" — валидный алиас только для parent_name, но
        # подстрочный проход не должен переиспользовать его для role.
        mapping = column_mapping.guess_mapping(["Родитель"])

        assigned = [key for key, header in mapping.items() if header == "Родитель"]
        self.assertEqual(assigned, ["parent_name"])

    def test_yo_and_ye_are_treated_as_equivalent(self):
        mapping = column_mapping.guess_mapping(["Фио ребенка"])

        self.assertEqual(mapping["child_name"], "Фио ребенка")

    def test_extra_whitespace_is_normalized(self):
        mapping = column_mapping.guess_mapping(["  ФИО   ребёнка  "])

        self.assertEqual(mapping["child_name"], "  ФИО   ребёнка  ")


class ReadXlsxTests(SimpleTestCase):
    def test_reads_headers_and_rows(self):
        file = _xlsx_bytes([["Данияр", "10.03.2018", "м", "Иванова", "+77011234567", ""]])

        headers, rows = column_mapping.read_xlsx(file)

        self.assertEqual(headers, HEADERS)
        self.assertEqual(len(rows), 1)
        row_number, values = rows[0]
        self.assertEqual(row_number, 2)
        self.assertEqual(values[0], "Данияр")

    def test_blank_row_is_skipped(self):
        file = _xlsx_bytes(
            [
                ["Данияр", "10.03.2018", "м", "Иванова", "+77011234567", ""],
                [None, None, None, None, None, None],
            ]
        )

        _, rows = column_mapping.read_xlsx(file)

        self.assertEqual(len(rows), 1)

    def test_merged_cells_are_backfilled_from_anchor(self):
        file = _xlsx_bytes(
            [
                ["Данияр", "10.03.2018", "м", "Иванова Марина", "+77011234567", "мама"],
                ["Айгерим", "01.01.2020", "ж", None, None, None],
            ],
            merges=("D2:D3", "E2:E3", "F2:F3"),
        )

        _, rows = column_mapping.read_xlsx(file)

        second_row_values = rows[1][1]
        self.assertEqual(second_row_values[3], "Иванова Марина")
        self.assertEqual(second_row_values[4], "+77011234567")
        self.assertEqual(second_row_values[5], "мама")


class ReadCsvTests(SimpleTestCase):
    def test_utf8_with_semicolon_delimiter(self):
        # utf-8-sig декодирует и обычный utf-8 без BOM (просто нечего
        # срезать) — он и оказывается первым успешным вариантом в цепочке.
        text = "ФИО ребёнка;Телефон родителя\nДанияр;+77011234567\n"
        file = io.BytesIO(text.encode("utf-8"))

        headers, rows, meta = column_mapping.read_csv(file)

        self.assertEqual(headers, ["ФИО ребёнка", "Телефон родителя"])
        self.assertEqual(rows[0][1], ["Данияр", "+77011234567"])
        self.assertEqual(meta["delimiter"], ";")
        self.assertEqual(meta["encoding"], "utf-8-sig")

    def test_utf8_sig_bom_is_detected(self):
        text = "ФИО ребёнка,Телефон родителя\nДанияр,+77011234567\n"
        file = io.BytesIO(text.encode("utf-8-sig"))

        headers, rows, meta = column_mapping.read_csv(file)

        self.assertEqual(headers, ["ФИО ребёнка", "Телефон родителя"])
        self.assertEqual(meta["encoding"], "utf-8-sig")

    def test_cp1251_windows_excel_export_is_decoded(self):
        # ТЗ явно: файлы из Excel в Windows приходят в cp1251 с точкой
        # с запятой — норма, а не исключение.
        text = "ФИО ребёнка;Телефон родителя\nДанияр;+77011234567\n"
        file = io.BytesIO(text.encode("cp1251"))

        headers, rows, meta = column_mapping.read_csv(file)

        self.assertEqual(headers, ["ФИО ребёнка", "Телефон родителя"])
        self.assertEqual(meta["encoding"], "cp1251")
        self.assertEqual(meta["delimiter"], ";")

    def test_comma_delimiter_is_detected(self):
        text = "ФИО ребёнка,Телефон родителя\nДанияр,+77011234567\n"
        file = io.BytesIO(text.encode("utf-8"))

        _, _, meta = column_mapping.read_csv(file)

        self.assertEqual(meta["delimiter"], ",")

    def test_blank_row_is_skipped(self):
        text = "ФИО ребёнка;Телефон родителя\nДанияр;+77011234567\n;\n"
        file = io.BytesIO(text.encode("utf-8"))

        _, rows, _ = column_mapping.read_csv(file)

        self.assertEqual(len(rows), 1)

    def test_empty_file_returns_empty_headers_and_rows(self):
        file = io.BytesIO(b"")

        headers, rows, meta = column_mapping.read_csv(file)

        self.assertEqual(headers, [])
        self.assertEqual(rows, [])


class ApplyMappingTests(SimpleTestCase):
    def test_maps_values_by_header_position(self):
        headers = ["Имя", "Телефон"]
        raw_rows = [(2, ["Данияр", "+77011234567"])]
        mapping = {"child_name": "Имя", "phone": "Телефон"}

        resolved = column_mapping.apply_mapping(headers, raw_rows, mapping)

        self.assertEqual(resolved, [(2, {"child_name": "Данияр", "phone": "+77011234567"})])

    def test_unmapped_field_is_absent_from_values(self):
        headers = ["Имя"]
        raw_rows = [(2, ["Данияр"])]
        mapping = {"child_name": "Имя", "phone": None}

        resolved = column_mapping.apply_mapping(headers, raw_rows, mapping)

        self.assertNotIn("phone", resolved[0][1])

    def test_short_row_missing_trailing_column_maps_to_none(self):
        headers = ["Имя", "Телефон"]
        raw_rows = [(2, ["Данияр"])]
        mapping = {"child_name": "Имя", "phone": "Телефон"}

        resolved = column_mapping.apply_mapping(headers, raw_rows, mapping)

        self.assertIsNone(resolved[0][1]["phone"])
