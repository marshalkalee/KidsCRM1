"""Публичный профиль центра и описание группы (TRU-179)."""

import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from domains.platform.tenants.models import Organization
from domains.platform.users.models import User

from .catalog import center_profile
from .models import CenterProfile
from .profile_views import normalize_instagram

URL = "/api/v1/api-keys/center-profile/"
MEDIA = tempfile.mkdtemp()


def png(name="logo.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


@override_settings(MEDIA_ROOT=MEDIA)
class CenterProfileTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="tb-profile")
        self.owner = self.user("77010000001", User.Role.OWNER)
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def user(self, phone, role):
        return User.objects.create_user(
            phone=phone, password="p", full_name=role, organization=self.org, role=role
        )

    def test_owner_fills_profile_and_values_are_normalized(self):
        data = self.api.patch(
            URL,
            {"description": "Балет для детей 4–14 лет", "phone": "8 701 111 22 33",
             "instagram": "https://www.instagram.com/trueballet/"},
            format="json",
        ).data  # fmt: skip
        self.assertEqual(data["instagram"], "trueballet")
        self.assertEqual(data["phone"], "+77011112233")
        self.assertEqual(normalize_instagram("@true.ballet"), "true.ballet")

    def test_publishing_needs_a_description(self):
        response = self.api.patch(URL, {"is_published": True}, format="json")
        self.assertEqual(response.status_code, 400)
        ok = self.api.patch(URL, {"description": "О нас", "is_published": True}, format="json")
        self.assertTrue(ok.data["is_published"])

    def test_only_owner(self):
        admin = APIClient()
        admin.force_authenticate(self.user("77010000002", User.Role.ADMIN))
        self.assertEqual(admin.get(URL).status_code, 403)

    def test_logo_replaced_and_old_file_removed(self):
        first = self.api.post(f"{URL}logo/", {"file": png()}, format="multipart").data["logo_url"]
        second = self.api.post(f"{URL}logo/", {"file": png()}, format="multipart").data["logo_url"]
        self.assertNotEqual(first, second)
        from django.core.files.storage import default_storage

        def stored(url):
            return default_storage.exists("centers/" + url.rsplit("centers/", 1)[1])

        self.assertFalse(stored(first))
        self.assertTrue(stored(second))

    def test_at_most_five_photos(self):
        for _ in range(CenterProfile.MAX_PHOTOS):
            self.api.post(f"{URL}photos/", {"file": png("p.png")}, format="multipart")
        response = self.api.post(f"{URL}photos/", {"file": png("p.png")}, format="multipart")
        self.assertEqual(response.status_code, 400)
        photos = CenterProfile.objects.get(organization=self.org).photo_urls
        self.api.delete(f"{URL}photos/", {"url": photos[0]}, format="json")
        self.assertEqual(len(CenterProfile.objects.get(organization=self.org).photo_urls), 4)

    def test_catalog_sees_profile_only_when_published(self):
        self.api.patch(URL, {"description": "О нас"}, format="json")
        self.assertIsNone(center_profile(self.org))
        self.api.patch(URL, {"is_published": True}, format="json")
        card = center_profile(self.org)
        self.assertEqual((card["name"], card["description"]), ("True Ballet", "О нас"))
        self.assertEqual(
            set(card), {"name", "description", "logo_url", "photo_urls", "phone", "instagram"}
        )
