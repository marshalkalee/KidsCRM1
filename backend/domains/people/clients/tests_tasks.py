"""
run_import_job (ТЗ п. 10.1) — импорт большого файла выполняется фоновой
задачей, не в HTTP-запросе. Задача вызывается здесь как обычная функция
(без .delay()/брокера) — так и предполагается тестировать celery-задачи,
см. https://docs.celeryq.dev/en/stable/userguide/testing.html; настоящий
проход через .delay() и воркер проверяется вручную (curl), не юнитами.
"""

import datetime

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from domains.platform.tenants.models import Organization

from .import_service import ImportRow
from .models import Child, ChildContact, ContactPhone, ImportColumnMapping, ImportJob, ParentContact
from .tasks import run_dry_run_job, run_import_job

User = get_user_model()


class ImportJobModelDefaultsTests(TestCase):
    def test_new_job_defaults_to_pending_with_zeroed_counts(self):
        org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        owner = User.objects.create_user(
            phone="+77010000001",
            full_name="Owner",
            password="pass12345",
            organization=org,
            role=User.Role.OWNER,
        )

        job = ImportJob.objects.create(
            organization=org, created_by=owner, total_rows=0, rows_payload=[]
        )

        self.assertEqual(job.status, ImportJob.Status.PENDING)
        self.assertEqual(job.job_type, ImportJob.JobType.EXECUTE)
        self.assertEqual(job.created_count, 0)
        self.assertEqual(job.attached_count, 0)
        self.assertEqual(job.skipped_count, 0)
        self.assertEqual(job.failed_rows, [])
        self.assertEqual(job.unhandled_balances, [])
        self.assertEqual(job.ready_count, 0)
        self.assertEqual(job.warning_count, 0)
        self.assertEqual(job.error_count, 0)
        self.assertEqual(job.report_rows, [])
        self.assertIsNone(job.finished_at)


class ImportColumnMappingUniquenessTests(TestCase):
    def test_two_active_mappings_with_same_headers_key_are_rejected(self):
        org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        ImportColumnMapping.objects.create(
            organization=org, headers_key="a|b", file_headers=["a", "b"], mapping={}
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ImportColumnMapping.objects.create(
                    organization=org, headers_key="a|b", file_headers=["a", "b"], mapping={}
                )


class RunImportJobTaskTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.owner = User.objects.create_user(
            phone="+77010000001",
            full_name="Owner",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )

    def _row_payload(self, row_number, name, phone, **extra):
        row = ImportRow(
            row_number=row_number,
            child_name=name,
            birth_date=datetime.date(2018, 3, 10),
            gender=Child.Gender.FEMALE,
            parent_name="Иванова Марина",
            phone=phone,
            role=ChildContact.Role.MOTHER,
        )
        for key, value in extra.items():
            setattr(row, key, value)
        return row.to_dict()

    def test_successful_job_creates_child_and_marks_done(self):
        job = ImportJob.objects.create(
            organization=self.org,
            created_by=self.owner,
            total_rows=1,
            rows_payload=[self._row_payload(2, "Данияр", "+77011234567")],
        )

        run_import_job(str(job.id))

        job.refresh_from_db()
        self.assertEqual(job.status, ImportJob.Status.DONE)
        self.assertEqual(job.created_count, 1)
        self.assertEqual(job.attached_count, 0)
        self.assertEqual(job.skipped_count, 0)
        self.assertIsNotNone(job.finished_at)
        self.assertEqual(Child.objects.for_tenant(self.org).count(), 1)

    def test_second_child_same_phone_is_attached_not_a_duplicate_family(self):
        job = ImportJob.objects.create(
            organization=self.org,
            created_by=self.owner,
            total_rows=2,
            rows_payload=[
                self._row_payload(2, "Данияр", "+77011234567"),
                self._row_payload(3, "Айгерим Серикова", "+77011234567"),
            ],
        )

        run_import_job(str(job.id))

        job.refresh_from_db()
        self.assertEqual(job.status, ImportJob.Status.DONE)
        self.assertEqual(job.created_count, 1)
        self.assertEqual(job.attached_count, 1)
        self.assertEqual(ParentContact.objects.for_tenant(self.org).count(), 1)
        self.assertEqual(Child.objects.for_tenant(self.org).count(), 2)

    def test_duplicate_against_existing_db_family_is_skipped(self):
        existing_child = Child.objects.create(
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
            organization=self.org,
            child=existing_child,
            parent_contact=parent,
            role=ChildContact.Role.MOTHER,
        )
        job = ImportJob.objects.create(
            organization=self.org,
            created_by=self.owner,
            total_rows=1,
            rows_payload=[self._row_payload(2, "Данияр", "+77011234567")],
        )

        run_import_job(str(job.id))

        job.refresh_from_db()
        self.assertEqual(job.status, ImportJob.Status.DONE)
        self.assertEqual(job.skipped_count, 1)
        self.assertEqual(Child.objects.for_tenant(self.org).count(), 1)

    def test_reported_balance_is_surfaced_on_the_job_not_imported(self):
        job = ImportJob.objects.create(
            organization=self.org,
            created_by=self.owner,
            total_rows=1,
            rows_payload=[self._row_payload(2, "Данияр", "+77011234567", reported_balance="5")],
        )

        run_import_job(str(job.id))

        job.refresh_from_db()
        self.assertEqual(job.unhandled_balances, [[2, "Данияр", "5"]])

    def test_row_with_parse_errors_is_counted_as_failed_not_created(self):
        job = ImportJob.objects.create(
            organization=self.org,
            created_by=self.owner,
            total_rows=1,
            rows_payload=[
                self._row_payload(2, "Данияр", "+77011234567", errors=["не заполнено ФИО родителя"])
            ],
        )

        run_import_job(str(job.id))

        job.refresh_from_db()
        self.assertEqual(job.status, ImportJob.Status.DONE)
        self.assertEqual(job.skipped_count, 1)
        self.assertEqual(Child.objects.for_tenant(self.org).count(), 0)

    def test_broken_rows_payload_marks_job_failed_with_error_message(self):
        # birth_date, который не парсится fromisoformat, — не может
        # случиться из настоящего build_row (там всегда либо валидный
        # isoformat, либо None), но задача должна пережить любую
        # поломку данных как FAILED, а не уронить воркер.
        job = ImportJob.objects.create(
            organization=self.org,
            created_by=self.owner,
            total_rows=1,
            rows_payload=[{"row_number": 2, "birth_date": "не дата"}],
        )

        run_import_job(str(job.id))

        job.refresh_from_db()
        self.assertEqual(job.status, ImportJob.Status.FAILED)
        self.assertTrue(job.error_message)
        self.assertIsNotNone(job.finished_at)


class RunDryRunJobTaskTests(TestCase):
    """Сухой прогон (ТЗ п. 4.1): дедуп читает базу (resolve_rows), но
    ни одна строка не создаёт Child/ParentContact — только отчёт на самой
    ImportJob."""

    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.owner = User.objects.create_user(
            phone="+77010000001",
            full_name="Owner",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )

    def _row_payload(self, row_number, name, phone, **extra):
        row = ImportRow(
            row_number=row_number,
            child_name=name,
            birth_date=datetime.date(2018, 3, 10),
            gender=Child.Gender.FEMALE,
            parent_name="Иванова Марина",
            phone=phone,
            role=ChildContact.Role.MOTHER,
        )
        for key, value in extra.items():
            setattr(row, key, value)
        return row.to_dict()

    def test_dry_run_creates_no_business_records(self):
        job = ImportJob.objects.create(
            organization=self.org,
            created_by=self.owner,
            job_type=ImportJob.JobType.DRY_RUN,
            total_rows=1,
            rows_payload=[self._row_payload(2, "Данияр", "+77011234567")],
        )

        run_dry_run_job(str(job.id))

        self.assertEqual(Child.objects.for_tenant(self.org).count(), 0)
        self.assertEqual(ParentContact.objects.for_tenant(self.org).count(), 0)

    def test_dry_run_reports_ready_row_and_marks_done(self):
        job = ImportJob.objects.create(
            organization=self.org,
            created_by=self.owner,
            job_type=ImportJob.JobType.DRY_RUN,
            total_rows=1,
            rows_payload=[self._row_payload(2, "Данияр", "+77011234567")],
        )

        run_dry_run_job(str(job.id))

        job.refresh_from_db()
        self.assertEqual(job.status, ImportJob.Status.DONE)
        self.assertEqual(job.ready_count, 1)
        self.assertEqual(job.warning_count, 0)
        self.assertEqual(job.error_count, 0)
        self.assertEqual(job.report_rows[0]["row_number"], 2)
        self.assertEqual(job.report_rows[0]["level"], "ready")

    def test_dry_run_finds_in_file_duplicate_as_warning(self):
        job = ImportJob.objects.create(
            organization=self.org,
            created_by=self.owner,
            job_type=ImportJob.JobType.DRY_RUN,
            total_rows=2,
            rows_payload=[
                self._row_payload(2, "Данияр", "+77011234567"),
                self._row_payload(3, "Данияр", "+77011234567"),
            ],
        )

        run_dry_run_job(str(job.id))

        job.refresh_from_db()
        self.assertEqual(job.ready_count, 1)
        self.assertEqual(job.warning_count, 1)
        self.assertEqual(job.report_rows[1]["level"], "warning")

    def test_dry_run_finds_duplicate_against_existing_db_child(self):
        existing_child = Child.objects.create(
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
            organization=self.org,
            child=existing_child,
            parent_contact=parent,
            role=ChildContact.Role.MOTHER,
        )
        job = ImportJob.objects.create(
            organization=self.org,
            created_by=self.owner,
            job_type=ImportJob.JobType.DRY_RUN,
            total_rows=1,
            rows_payload=[self._row_payload(2, "Данияр", "+77011234567")],
        )

        run_dry_run_job(str(job.id))

        job.refresh_from_db()
        self.assertEqual(job.warning_count, 1)
        self.assertEqual(job.ready_count, 0)

    def test_dry_run_reports_row_with_errors(self):
        job = ImportJob.objects.create(
            organization=self.org,
            created_by=self.owner,
            job_type=ImportJob.JobType.DRY_RUN,
            total_rows=1,
            rows_payload=[
                self._row_payload(147, "", "+77011234567", errors=["не заполнено ФИО ребёнка"])
            ],
        )

        run_dry_run_job(str(job.id))

        job.refresh_from_db()
        self.assertEqual(job.error_count, 1)
        self.assertEqual(job.report_rows[0]["row_number"], 147)
        self.assertEqual(job.report_rows[0]["messages"], ["не заполнено ФИО ребёнка"])

    def test_broken_rows_payload_marks_dry_run_job_failed(self):
        job = ImportJob.objects.create(
            organization=self.org,
            created_by=self.owner,
            job_type=ImportJob.JobType.DRY_RUN,
            total_rows=1,
            rows_payload=[{"row_number": 2, "birth_date": "не дата"}],
        )

        run_dry_run_job(str(job.id))

        job.refresh_from_db()
        self.assertEqual(job.status, ImportJob.Status.FAILED)
        self.assertTrue(job.error_message)
