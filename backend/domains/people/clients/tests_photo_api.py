"""POST /api/v1/clients/children/photo/ — фото ребёнка для формы frontend2."""

import io
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image
from rest_framework.test import APIClient

from domains.platform.tenants.models import Organization

from .photos import MAX_PHOTO_BYTES

User = get_user_model()
URL = reverse("clients:child-photo")
MEDIA = tempfile.mkdtemp()


def png(name="photo.png"):
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "#e8998d").save(buf, "PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


@override_settings(MEDIA_ROOT=MEDIA)
class ChildPhotoApiTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        make = lambda phone, role: User.objects.create_user(  # noqa: E731
            phone=phone, full_name=role, password="pass12345", organization=org, role=role
        )
        self.owner = make("+77010000001", "owner")
        self.teacher = make("+77010000002", "teacher")
        self.api = APIClient()

    def test_owner_uploads_image_and_gets_absolute_url(self):
        self.api.force_authenticate(self.owner)

        response = self.api.post(URL, {"file": png()}, format="multipart")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(
            response.json()["url"].startswith("http://testserver/media/children/photos/")
        )
        self.assertTrue(response.json()["url"].endswith(".png"))

    def test_not_an_image_is_rejected(self):
        self.api.force_authenticate(self.owner)
        fake = SimpleUploadedFile("photo.png", b"not an image", content_type="image/png")

        response = self.api.post(URL, {"file": fake}, format="multipart")

        self.assertEqual(response.status_code, 400)

    def test_too_big_is_rejected(self):
        self.api.force_authenticate(self.owner)
        big = SimpleUploadedFile("big.png", b"0" * (MAX_PHOTO_BYTES + 1), content_type="image/png")

        response = self.api.post(URL, {"file": big}, format="multipart")

        self.assertEqual(response.status_code, 400)
        self.assertIn("5 МБ", response.json()["file"][0])

    def test_teacher_and_anonymous_cannot_upload(self):
        self.assertEqual(self.api.post(URL, {"file": png()}, format="multipart").status_code, 401)
        self.api.force_authenticate(self.teacher)
        self.assertEqual(self.api.post(URL, {"file": png()}, format="multipart").status_code, 403)
