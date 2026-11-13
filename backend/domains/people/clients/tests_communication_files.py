"""Заметки «Коммуникаций»: файлы и связь родитель ↔ дети."""

import datetime
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from domains.platform.tenants.models import Organization
from domains.platform.users.models import User

from .models import Child, ChildContact, CommunicationAttachment, ParentContact

URL = "/api/v1/clients/communications/"
MEDIA = tempfile.mkdtemp(prefix="kidscrm-test-media-")


@override_settings(MEDIA_ROOT=MEDIA)
class CommunicationFilesTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.org = Organization.objects.create(name="Центр", slug="files-test")
        self.parent = ParentContact.objects.create(organization=self.org, full_name="Исаева Мария")
        self.child = Child.objects.create(
            organization=self.org, full_name="Милана Исаева", birth_date=datetime.date(2016, 4, 5)
        )
        ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=self.parent,
            role=ChildContact.Role.MOTHER,
        )
        self.owner = User.objects.create_user(
            phone="77009990011",
            password="password",
            full_name="Владелец",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def post(self, files=(), **data):
        payload = {"channel": "comment", "note": "Справка о болезни", **data}
        if files:
            payload["files"] = list(files)
        return self.api.post(URL, payload, format="multipart")

    def test_note_with_file_and_download(self):
        pdf = SimpleUploadedFile("справка.pdf", b"%PDF-1.4 test", content_type="application/pdf")
        response = self.post([pdf], child=str(self.child.id))
        self.assertEqual(response.status_code, 201, response.data)
        attachment = response.data["attachments"][0]
        self.assertEqual(attachment["name"], "справка.pdf")
        file_response = self.api.get(f"{URL}{response.data['id']}/files/{attachment['id']}/")
        self.assertEqual(file_response.status_code, 200)
        self.assertEqual(b"".join(file_response.streaming_content), b"%PDF-1.4 test")

    def test_other_center_cannot_download(self):
        pdf = SimpleUploadedFile("справка.pdf", b"%PDF", content_type="application/pdf")
        response = self.post([pdf], child=str(self.child.id))
        attachment = CommunicationAttachment.objects.get()
        other_org = Organization.objects.create(name="Чужой", slug="files-other")
        stranger = User.objects.create_user(
            phone="77009990012",
            password="password",
            full_name="Чужой",
            organization=other_org,
            role=User.Role.OWNER,
        )
        self.api.force_authenticate(stranger)
        file_response = self.api.get(f"{URL}{response.data['id']}/files/{attachment.id}/")
        self.assertEqual(file_response.status_code, 404)

    def test_executable_and_too_many_files_are_rejected(self):
        exe = SimpleUploadedFile("virus.exe", b"MZ", content_type="application/octet-stream")
        self.assertEqual(self.post([exe], child=str(self.child.id)).status_code, 400)
        many = [SimpleUploadedFile(f"{i}.png", b"png", content_type="image/png") for i in range(6)]
        self.assertEqual(self.post(many, child=str(self.child.id)).status_code, 400)
        self.assertFalse(CommunicationAttachment.objects.exists())

    def test_note_about_parent_is_seen_on_child_card_and_back(self):
        self.post(parent_contact=str(self.parent.id), note="Мама просила звонить после 18:00")
        self.post(child=str(self.child.id), note="Пропустила неделю")
        child_notes = {
            row["note"] for row in self.api.get(URL, {"child": str(self.child.id)}).data["results"]
        }
        parent_notes = {
            row["note"]
            for row in self.api.get(URL, {"family": str(self.parent.id)}).data["results"]
        }
        expected = {"Мама просила звонить после 18:00", "Пропустила неделю"}
        self.assertEqual(child_notes, expected)
        self.assertEqual(parent_notes, expected)
