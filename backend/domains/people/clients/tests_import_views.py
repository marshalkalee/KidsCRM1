"""
Веб-экран импорта (import_views.py) — загрузка/предпросмотр/подтверждение
через настоящий HTTP-клиент (multipart-загрузка файла), не только
юниты сервисов (см. tests_import_service.py/tests_services.py).
"""

import datetime
import io
import json

import openpyxl
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from domains.platform.tenants.models import Organization

from .models import Child, ChildContact, ContactPhone, ParentContact

User = get_user_model()

HEADERS = [
    "ФИО ребёнка",
    "Дата рождения ребёнка",
    "Пол ребёнка",
    "ФИО родителя",
    "Телефон родителя",
    "Роль родителя",
]


def _xlsx_file(rows, headers=HEADERS):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return SimpleUploadedFile(
        "import.xlsx",
        buf.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


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

    def test_rejects_non_xlsx_extension(self):
        self.client.force_login(self.owner)
        bad_file = SimpleUploadedFile("import.csv", b"not,excel", content_type="text/csv")

        response = self.client.post(reverse("clients_web:child-import-upload"), {"file": bad_file})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "xlsx")

    def test_valid_upload_shows_preview_with_new_row(self):
        self.client.force_login(self.owner)
        file = _xlsx_file([["Данияр", "10.03.2018", "м", "Иванова Марина", "+77011234567", "мама"]])

        response = self.client.post(reverse("clients_web:child-import-upload"), {"file": file})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Данияр")
        self.assertContains(response, "rows_json")

    def test_upload_missing_header_shows_form_error(self):
        self.client.force_login(self.owner)
        headers = [h for h in HEADERS if h != "Телефон родителя"]
        file = _xlsx_file([["Данияр", "10.03.2018", "м", "Иванова", "мама"]], headers=headers)

        response = self.client.post(reverse("clients_web:child-import-upload"), {"file": file})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Телефон родителя")
        self.assertEqual(Child.objects.for_tenant(self.org).count(), 0)

    def test_upload_flags_second_child_of_existing_family(self):
        existing_child = Child.objects.create(
            organization=self.org,
            full_name="Данияр",
            birth_date=datetime.date(2016, 1, 1),
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
        self.client.force_login(self.owner)
        file = _xlsx_file(
            [["Айгерим", "01.01.2020", "ж", "Иванова Марина", "+77011234567", "мама"]]
        )

        response = self.client.post(reverse("clients_web:child-import-upload"), {"file": file})

        self.assertContains(response, "attach_existing")
        self.assertContains(response, "selected")


class ChildImportConfirmViewTests(TestCase):
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

    def _confirm(self, rows, overrides=None):
        overrides = overrides or {}
        data = {"rows_json": json.dumps(rows)}
        data.update(overrides)
        return self.client.post(reverse("clients_web:child-import-confirm"), data)

    def test_confirm_creates_child_and_parent(self):
        rows = [
            {
                "row_number": 2,
                "child_name": "Данияр",
                "birth_date": "2018-03-10",
                "gender": "male",
                "parent_name": "Иванова Марина",
                "phone": "+77011234567",
                "role": "mother",
                "action": "create_new_family",
                "matched_parent_id": None,
            }
        ]

        response = self._confirm(rows)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Child.objects.for_tenant(self.org).count(), 1)
        self.assertContains(response, "1")

    def test_confirm_honors_admin_override_to_skip(self):
        rows = [
            {
                "row_number": 2,
                "child_name": "Данияр",
                "birth_date": "2018-03-10",
                "gender": "male",
                "parent_name": "Иванова Марина",
                "phone": "+77011234567",
                "role": "mother",
                "action": "create_new_family",
                "matched_parent_id": None,
            }
        ]

        self._confirm(rows, overrides={"action_2": "skip"})

        self.assertEqual(Child.objects.for_tenant(self.org).count(), 0)

    def test_confirm_attaches_second_child_to_existing_parent(self):
        existing_child = Child.objects.create(
            organization=self.org,
            full_name="Данияр",
            birth_date=datetime.date(2016, 1, 1),
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
        rows = [
            {
                "row_number": 2,
                "child_name": "Айгерим",
                "birth_date": "2020-01-01",
                "gender": "female",
                "parent_name": "Иванова Марина",
                "phone": "+77011234567",
                "role": "mother",
                "action": "attach_existing",
                "matched_parent_id": str(parent.id),
            }
        ]

        self._confirm(rows)

        self.assertEqual(ParentContact.objects.for_tenant(self.org).count(), 1)
        self.assertEqual(Child.objects.for_tenant(self.org).count(), 2)

    def test_invalid_rows_json_redirects_to_upload(self):
        response = self.client.post(
            reverse("clients_web:child-import-confirm"), {"rows_json": "not json"}
        )

        self.assertRedirects(response, reverse("clients_web:child-import-upload"))
