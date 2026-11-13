"""Заметки заявки с файлами."""

import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from domains.platform.tenants.models import Organization
from domains.platform.users.models import User

from .models import Lead

MEDIA = tempfile.mkdtemp(prefix="kidscrm-lead-files-")


@override_settings(MEDIA_ROOT=MEDIA)
class LeadCommentFilesTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.org = Organization.objects.create(name="Центр", slug="lead-files")
        self.lead = Lead.objects.create(
            organization=self.org, parent_name="Айгерим", phone="+77011112233"
        )
        self.owner = User.objects.create_user(
            phone="77009990021",
            password="password",
            full_name="Владелец",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.url = f"/api/v1/leads/{self.lead.id}/comments/"

    def test_note_with_photo_and_download(self):
        photo = SimpleUploadedFile("договор.jpg", b"jpeg", content_type="image/jpeg")
        response = self.api.post(
            self.url, {"text": "Прислала договор", "files": [photo]}, format="multipart"
        )
        self.assertEqual(response.status_code, 201, response.data)
        file = response.data["attachments"][0]
        self.assertEqual(file["name"], "договор.jpg")
        listing = self.api.get(self.url).data
        self.assertEqual(listing[0]["attachments"][0]["id"], file["id"])
        download = self.api.get(f"{self.url}{response.data['id']}/files/{file['id']}/")
        self.assertEqual(b"".join(download.streaming_content), b"jpeg")

    def test_plain_note_still_works_and_exe_rejected(self):
        response = self.api.post(self.url, {"text": "Перезвонить"}, format="json")
        self.assertEqual(response.status_code, 201)
        exe = SimpleUploadedFile("x.exe", b"MZ", content_type="application/octet-stream")
        response = self.api.post(self.url, {"text": "x", "files": [exe]}, format="multipart")
        self.assertEqual(response.status_code, 400)
