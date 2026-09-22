"""
Веб-экраны импорта (import_views.py) через настоящий HTTP-клиент
(multipart-загрузка файла), не только юниты сервисов (см.
tests_import_service.py/tests_column_mapping.py/tests_tasks.py).
Три шага: загрузка -> маппинг -> сводка -> запуск фоновой задачи ->
статус задачи (ТЗ п. 4.1, п. 10.1).
"""

import io
from unittest import mock

import openpyxl
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from domains.platform.tenants.models import Organization

from .models import Child, ImportColumnMapping, ImportJob
from .tasks import run_import_job

User = get_user_model()

HEADERS = [
    "ФИО ребёнка",
    "Дата рождения ребёнка",
    "Пол ребёнка",
    "ФИО родителя",
    "Телефон родителя",
    "Роль родителя",
]


def _xlsx_file(rows, headers=HEADERS, filename="import.xlsx"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return SimpleUploadedFile(
        filename,
        buf.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _mapping_dict(mapping_rows):
    return {key: current for key, _, _, current in mapping_rows}


class ChildImportUploadViewTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.owner = User.objects.create_user(
            phone="+77010000001",
            full_name="Owner",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.teacher = User.objects.create_user(
            phone="+77010000002",
            full_name="Teacher",
            password="pass12345",
            organization=self.org,
            role=User.Role.TEACHER,
        )

    def test_get_renders_upload_form(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("clients_web:child-import-upload"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'enctype="multipart/form-data"')

    def test_teacher_cannot_access_upload(self):
        self.client.force_login(self.teacher)

        response = self.client.get(reverse("clients_web:child-import-upload"))

        self.assertEqual(response.status_code, 403)

    def test_rejects_unsupported_extension(self):
        self.client.force_login(self.owner)
        bad_file = SimpleUploadedFile("import.txt", b"not a spreadsheet", content_type="text/plain")

        response = self.client.post(reverse("clients_web:child-import-upload"), {"file": bad_file})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "xlsx")

    def test_valid_xlsx_upload_shows_mapping_screen_with_guessed_columns(self):
        self.client.force_login(self.owner)
        file = _xlsx_file([["Данияр", "10.03.2018", "м", "Иванова Марина", "+77011234567", "мама"]])

        response = self.client.post(reverse("clients_web:child-import-upload"), {"file": file})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Данияр")
        mapping = _mapping_dict(response.context["mapping_rows"])
        self.assertEqual(mapping["child_name"], "ФИО ребёнка")
        self.assertEqual(mapping["phone"], "Телефон родителя")

    def test_valid_csv_upload_detects_cp1251_and_semicolon(self):
        # ТЗ явно: файлы из Excel в Windows приходят в cp1251 с точкой
        # с запятой — норма, не исключение.
        self.client.force_login(self.owner)
        text = (
            "ФИО ребёнка;Дата рождения ребёнка;Пол ребёнка;ФИО родителя;"
            "Телефон родителя;Роль родителя\n"
            "Данияр;10.03.2018;м;Иванова Марина;+77011234567;мама\n"
        )
        file = SimpleUploadedFile("import.csv", text.encode("cp1251"), content_type="text/csv")

        response = self.client.post(reverse("clients_web:child-import-upload"), {"file": file})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cp1251")
        self.assertContains(response, "Данияр")

    def test_empty_file_shows_form_error(self):
        self.client.force_login(self.owner)
        file = _xlsx_file([])

        response = self.client.post(reverse("clients_web:child-import-upload"), {"file": file})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "не нашлось")

    def test_saved_mapping_is_reused_on_next_upload_of_same_columns(self):
        # Критерий приёмки: повторный импорт с тем же составом колонок
        # не требует настраивать маппинг заново.
        self.client.force_login(self.owner)
        custom_headers = ["Child", "DOB", "Sex", "Parent", "Contact Data", "Relation"]
        file = _xlsx_file(
            [["Данияр", "10.03.2018", "м", "Иванова Марина", "+77011234567", "мама"]],
            headers=custom_headers,
        )

        first_upload = self.client.post(reverse("clients_web:child-import-upload"), {"file": file})
        first_mapping = _mapping_dict(first_upload.context["mapping_rows"])
        self.assertIsNone(first_mapping["phone"])  # "Contact Data" угадать нечем

        confirm_data = {
            "headers_json": first_upload.context["headers_json"],
            "raw_rows_json": first_upload.context["raw_rows_json"],
            "meta_json": first_upload.context["meta_json"],
            "mapping_child_name": "Child",
            "mapping_birth_date": "DOB",
            "mapping_gender": "Sex",
            "mapping_parent_name": "Parent",
            "mapping_phone": "Contact Data",
            "mapping_role": "Relation",
        }
        self.client.post(reverse("clients_web:child-import-mapping-confirm"), confirm_data)

        second_file = _xlsx_file(
            [["Айгерим", "01.01.2020", "ж", "Иванова Марина", "+77011234567", "мама"]],
            headers=custom_headers,
        )
        second_upload = self.client.post(
            reverse("clients_web:child-import-upload"), {"file": second_file}
        )

        second_mapping = _mapping_dict(second_upload.context["mapping_rows"])
        self.assertEqual(second_mapping["phone"], "Contact Data")


class ChildImportMappingConfirmViewTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.owner = User.objects.create_user(
            phone="+77010000001",
            full_name="Owner",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.client.force_login(self.owner)

    def _upload(self, rows, headers=HEADERS):
        return self.client.post(
            reverse("clients_web:child-import-upload"), {"file": _xlsx_file(rows, headers=headers)}
        )

    def _full_mapping_data(self, upload_response):
        data = {
            "headers_json": upload_response.context["headers_json"],
            "raw_rows_json": upload_response.context["raw_rows_json"],
            "meta_json": upload_response.context["meta_json"],
        }
        for key, current in _mapping_dict(upload_response.context["mapping_rows"]).items():
            if current:
                data[f"mapping_{key}"] = current
        return data

    def test_confirm_with_full_mapping_shows_summary(self):
        upload = self._upload(
            [["Данияр", "10.03.2018", "м", "Иванова Марина", "+77011234567", "мама"]]
        )

        response = self.client.post(
            reverse("clients_web:child-import-mapping-confirm"), self._full_mapping_data(upload)
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["valid_count"], 1)
        self.assertEqual(response.context["error_count"], 0)

    def test_confirm_reports_invalid_rows_separately(self):
        upload = self._upload(
            [
                ["Данияр", "10.03.2018", "м", "Иванова Марина", "+77011234567", "мама"],
                ["", "не дата", "?", "", "не телефон", ""],
            ]
        )

        response = self.client.post(
            reverse("clients_web:child-import-mapping-confirm"), self._full_mapping_data(upload)
        )

        self.assertEqual(response.context["valid_count"], 1)
        self.assertEqual(response.context["error_count"], 1)

    def test_confirm_missing_required_field_rerenders_mapping_with_error(self):
        upload = self._upload(
            [["Данияр", "10.03.2018", "м", "Иванова Марина", "+77011234567", "мама"]]
        )
        data = {
            "headers_json": upload.context["headers_json"],
            "raw_rows_json": upload.context["raw_rows_json"],
            "meta_json": upload.context["meta_json"],
            "mapping_child_name": "ФИО ребёнка",
        }

        response = self.client.post(reverse("clients_web:child-import-mapping-confirm"), data)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Телефон родителя", response.context["missing_required"])
        self.assertEqual(Child.objects.for_tenant(self.org).count(), 0)

    def test_confirm_saves_mapping_for_reuse(self):
        upload = self._upload(
            [["Данияр", "10.03.2018", "м", "Иванова Марина", "+77011234567", "мама"]]
        )

        self.client.post(
            reverse("clients_web:child-import-mapping-confirm"), self._full_mapping_data(upload)
        )

        self.assertEqual(ImportColumnMapping.objects.for_tenant(self.org).count(), 1)

    def test_invalid_json_redirects_to_upload(self):
        response = self.client.post(
            reverse("clients_web:child-import-mapping-confirm"), {"headers_json": "not json"}
        )

        self.assertRedirects(response, reverse("clients_web:child-import-upload"))


class ChildImportStartViewTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.owner = User.objects.create_user(
            phone="+77010000001",
            full_name="Owner",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.client.force_login(self.owner)
        # .delay() требует брокера (Redis) — здесь задача выполняется
        # синхронно в процессе теста через apply(), без брокера и без
        # изменения кода вьюхи/задачи (см. tests_tasks.py про сам
        # run_import_job, а настоящий проход через воркер — curl-проверка).
        patcher = mock.patch.object(
            run_import_job, "delay", side_effect=lambda job_id: run_import_job.apply(args=[job_id])
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _summary_response(self, rows, headers=HEADERS):
        upload = self.client.post(
            reverse("clients_web:child-import-upload"), {"file": _xlsx_file(rows, headers=headers)}
        )
        data = {
            "headers_json": upload.context["headers_json"],
            "raw_rows_json": upload.context["raw_rows_json"],
            "meta_json": upload.context["meta_json"],
        }
        for key, current in _mapping_dict(upload.context["mapping_rows"]).items():
            if current:
                data[f"mapping_{key}"] = current
        return self.client.post(reverse("clients_web:child-import-mapping-confirm"), data)

    def test_start_creates_job_and_redirects_to_status(self):
        summary = self._summary_response(
            [["Данияр", "10.03.2018", "м", "Иванова Марина", "+77011234567", "мама"]]
        )

        response = self.client.post(
            reverse("clients_web:child-import-start"),
            {"valid_rows_json": summary.context["valid_rows_json"]},
        )

        job = ImportJob.objects.for_tenant(self.org).get()
        self.assertRedirects(
            response, reverse("clients_web:child-import-job-status", args=[job.id])
        )
        self.assertEqual(job.total_rows, 1)

    def test_started_job_runs_and_creates_the_child(self):
        summary = self._summary_response(
            [["Данияр", "10.03.2018", "м", "Иванова Марина", "+77011234567", "мама"]]
        )

        self.client.post(
            reverse("clients_web:child-import-start"),
            {"valid_rows_json": summary.context["valid_rows_json"]},
        )

        job = ImportJob.objects.for_tenant(self.org).get()
        self.assertEqual(job.status, ImportJob.Status.DONE)
        self.assertEqual(job.created_count, 1)
        self.assertEqual(Child.objects.for_tenant(self.org).count(), 1)

    def test_invalid_json_redirects_to_upload(self):
        response = self.client.post(
            reverse("clients_web:child-import-start"), {"valid_rows_json": "not json"}
        )

        self.assertRedirects(response, reverse("clients_web:child-import-upload"))


class ChildImportJobStatusViewTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.other_org = Organization.objects.create(name="Other Studio", slug="other-studio")
        self.owner = User.objects.create_user(
            phone="+77010000001",
            full_name="Owner",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.client.force_login(self.owner)

    def test_pending_job_shows_in_progress_message(self):
        job = ImportJob.objects.create(
            organization=self.org, created_by=self.owner, total_rows=1, rows_payload=[]
        )

        response = self.client.get(reverse("clients_web:child-import-job-status", args=[job.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ожидает")

    def test_done_job_shows_result_counts(self):
        job = ImportJob.objects.create(
            organization=self.org,
            created_by=self.owner,
            total_rows=1,
            rows_payload=[],
            status=ImportJob.Status.DONE,
            created_count=1,
        )

        response = self.client.get(reverse("clients_web:child-import-job-status", args=[job.id]))

        self.assertContains(response, "Готово")

    def test_failed_job_shows_error_message(self):
        job = ImportJob.objects.create(
            organization=self.org,
            created_by=self.owner,
            total_rows=1,
            rows_payload=[],
            status=ImportJob.Status.FAILED,
            error_message="Что-то сломалось",
        )

        response = self.client.get(reverse("clients_web:child-import-job-status", args=[job.id]))

        self.assertContains(response, "Что-то сломалось")

    def test_job_from_another_organization_is_not_visible(self):
        job = ImportJob.objects.create(
            organization=self.other_org, created_by=self.owner, total_rows=1, rows_payload=[]
        )

        response = self.client.get(reverse("clients_web:child-import-job-status", args=[job.id]))

        self.assertEqual(response.status_code, 404)
