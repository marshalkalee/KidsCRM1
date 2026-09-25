"""
API импорта (import_api_views.py, для frontend2) — тот же жизненный цикл,
что у веб-экранов: сухой прогон → решения по дублям → транзакционный
импорт → откат.
"""

import datetime
import io
import json

import openpyxl
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from domains.platform.tenants.models import Organization

from .models import (
    Child,
    ChildContact,
    CommunicationLog,
    ContactPhone,
    ImportJob,
    ParentContact,
)
from .tests_import_views import _run_celery_tasks_synchronously, _xlsx_file

User = get_user_model()


class ImportApiBase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.owner = User.objects.create_user(
            phone="+77010000001",
            full_name="Owner",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        for patcher in _run_celery_tasks_synchronously():
            self.addCleanup(patcher.stop)
        # Существующая семья: в файле новый ребёнок этой мамы — совпадение
        # «родитель уже есть в базе».
        child = Child.objects.create(
            organization=self.org,
            full_name="Данияр",
            birth_date=datetime.date(2018, 3, 10),
            gender=Child.Gender.MALE,
        )
        parent = ParentContact.objects.create(organization=self.org, full_name="Иванова Марина")
        ContactPhone.objects.create(
            organization=self.org, parent_contact=parent, number="+77011234567"
        )
        ChildContact.objects.create(
            organization=self.org, child=child, parent_contact=parent, role="mother"
        )

    def _preview(self):
        file = _xlsx_file(
            [
                ["Айгерим", "01.02.2017", "ж", "Иванова Марина", "+77011234567", "мама"],
                ["Алия", "05.05.2019", "ж", "Сейтова Алма", "+77019998877", "мама"],
                ["", "не дата", "?", "", "", ""],
            ]
        )
        return self.client.post(
            reverse("clients:import-preview"), {"file": file}, format="multipart"
        )


class ImportApiTests(ImportApiBase):
    def test_preview_runs_dry_run_and_writes_nothing(self):
        response = self._preview()

        self.assertEqual(response.status_code, 202)
        job = self.client.get(
            reverse("clients:import-job-detail", args=[response.data["job_id"]])
        ).data
        self.assertEqual(job["status"], "done")
        self.assertEqual((job["ready_count"], job["error_count"]), (2, 1))
        duplicate = next(row for row in job["rows"] if row["duplicate"])
        self.assertEqual(duplicate["duplicate"]["kind"], "family")
        self.assertIn("attach", duplicate["duplicate"]["option_labels"])
        self.assertEqual(Child.objects.for_tenant(self.org).count(), 1)

    def test_confirm_applies_decisions_and_imports(self):
        dry_run_id = self._preview().data["job_id"]

        response = self.client.post(
            reverse("clients:import-confirm"),
            {"job_id": dry_run_id, "decisions": {"2": "create_new"}},
            format="json",
        )

        self.assertEqual(response.status_code, 202)
        result = self.client.get(
            reverse("clients:import-job-detail", args=[response.data["job_id"]])
        ).data
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["children_created"], 2)
        # «Создать нового родителя» вместо привязки к существующей маме.
        self.assertEqual(result["parents_created"], 2)
        self.assertEqual(Child.objects.for_tenant(self.org).count(), 3)

    def test_second_confirm_does_not_import_twice(self):
        dry_run_id = self._preview().data["job_id"]
        first = self.client.post(
            reverse("clients:import-confirm"), {"job_id": dry_run_id}, format="json"
        )

        second = self.client.post(
            reverse("clients:import-confirm"), {"job_id": dry_run_id}, format="json"
        )

        self.assertEqual(first.data["job_id"], second.data["job_id"])
        self.assertEqual(Child.objects.for_tenant(self.org).count(), 3)

    def test_rollback_via_api(self):
        dry_run_id = self._preview().data["job_id"]
        execute_id = self.client.post(
            reverse("clients:import-confirm"), {"job_id": dry_run_id}, format="json"
        ).data["job_id"]

        response = self.client.post(reverse("clients:import-rollback", args=[execute_id]))

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.data["rolled_back_at"])
        self.assertEqual(Child.objects.for_tenant(self.org).count(), 1)

    def test_bad_job_id_is_404_not_500(self):
        response = self.client.post(
            reverse("clients:import-confirm"), {"job_id": "not-a-uuid"}, format="json"
        )

        self.assertEqual(response.status_code, 404)

    def test_other_organizations_job_is_not_visible(self):
        dry_run_id = self._preview().data["job_id"]
        other_org = Organization.objects.create(name="Other", slug="other")
        other_owner = User.objects.create_user(
            phone="+77010000009",
            full_name="Other",
            password="pass12345",
            organization=other_org,
            role=User.Role.OWNER,
        )
        self.client.force_authenticate(other_owner)

        response = self.client.get(reverse("clients:import-job-detail", args=[dry_run_id]))
        confirm = self.client.post(
            reverse("clients:import-confirm"), {"job_id": dry_run_id}, format="json"
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(confirm.status_code, 404)
        self.assertFalse(ImportJob.objects.filter(job_type="execute").exists())

    def test_teacher_cannot_import(self):
        teacher = User.objects.create_user(
            phone="+77010000002",
            full_name="Teacher",
            password="pass12345",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        self.client.force_authenticate(teacher)

        response = self._preview()

        self.assertEqual(response.status_code, 403)


# Нестандартные заголовки — автоматически не угадываются.
ODD_HEADERS = ["Воспитанник", "ДР", "М/Ж", "Кто привёл", "Контакт"]
ODD_MAPPING = {
    "child_name": "Воспитанник",
    "birth_date": "ДР",
    "gender": "М/Ж",
    "parent_name": "Кто привёл",
    "phone": "Контакт",
}


class ImportMappingApiTests(ImportApiBase):
    """Экран маппинга (analyze/ → preview/ с mapping), массовые решения,
    отчёт файлом, история и причины отказа в откате (TRU-84)."""

    def _odd_file(self):
        return _xlsx_file(
            [["Айгерим", "01.02.2017", "ж", "Сейтова Алма", "+77019998877"]], headers=ODD_HEADERS
        )

    def test_analyze_returns_headers_preview_and_missing_fields(self):
        response = self.client.post(
            reverse("clients:import-analyze"), {"file": self._odd_file()}, format="multipart"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["headers"], ODD_HEADERS)
        self.assertFalse(response.data["mapping_saved"])
        self.assertIn("ФИО ребёнка", response.data["missing_required"])
        self.assertEqual(response.data["preview_rows"][0]["values"][0], "Айгерим")
        self.assertEqual(response.data["total_rows"], 1)
        self.assertEqual(ImportJob.objects.count(), 0)

    def test_manual_mapping_imports_and_is_remembered(self):
        response = self.client.post(
            reverse("clients:import-preview"),
            {"file": self._odd_file(), "mapping": json.dumps(ODD_MAPPING)},
            format="multipart",
        )
        self.assertEqual(response.status_code, 202, response.data)
        job = self.client.get(
            reverse("clients:import-job-detail", args=[response.data["job_id"]])
        ).data
        self.assertEqual(job["ready_count"], 1)

        again = self.client.post(
            reverse("clients:import-analyze"), {"file": self._odd_file()}, format="multipart"
        )
        self.assertTrue(again.data["mapping_saved"])
        self.assertEqual(again.data["missing_required"], [])
        self.assertEqual(again.data["mapping"]["phone"], "Контакт")

    def test_mapping_without_required_field_is_400(self):
        partial = {**ODD_MAPPING, "phone": None}
        response = self.client.post(
            reverse("clients:import-preview"),
            {"file": self._odd_file(), "mapping": json.dumps(partial)},
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("mapping", response.data)

    def test_bulk_decision_applies_to_all_rows_of_kind(self):
        dry_run_id = self._preview().data["job_id"]
        job = self.client.get(reverse("clients:import-job-detail", args=[dry_run_id])).data
        self.assertEqual(job["duplicate_kinds"][0]["kind"], "family")

        response = self.client.post(
            reverse("clients:import-decisions", args=[dry_run_id]),
            {"bulk_kind": "family", "bulk_decision": "create_new"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["decisions"], {"2": "create_new"})

    def test_report_downloads_as_xlsx(self):
        dry_run_id = self._preview().data["job_id"]

        response = self.client.get(reverse("clients:import-report", args=[dry_run_id]))

        self.assertEqual(response.status_code, 200)
        workbook = openpyxl.load_workbook(io.BytesIO(response.content))
        self.assertGreater(workbook.active.max_row, 1)

    def test_history_and_rollback_blockers(self):
        dry_run_id = self._preview().data["job_id"]
        execute_id = self.client.post(
            reverse("clients:import-confirm"), {"job_id": dry_run_id}, format="json"
        ).data["job_id"]
        child = Child.objects.for_tenant(self.org).get(full_name="Алия")
        CommunicationLog.objects.create(child=child, note="звонили", author=self.owner)

        history = self.client.get(reverse("clients:import-jobs")).data["results"]
        detail = self.client.get(reverse("clients:import-job-detail", args=[execute_id])).data
        rollback = self.client.post(reverse("clients:import-rollback", args=[execute_id]))

        self.assertEqual([h["job_id"] for h in history], [execute_id])
        self.assertTrue(detail["rollback_blockers"])
        self.assertEqual(rollback.status_code, 409)
        self.assertIn("коммуникаций", rollback.data["detail"])
