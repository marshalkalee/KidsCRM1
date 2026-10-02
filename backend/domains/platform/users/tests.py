import io
import shutil
import tempfile
from pathlib import Path

from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings, tag
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from domains.platform.tenants.models import Branch, Organization

from .models import User


class UserModelTests(APITestCase):
    def test_user_can_be_attached_to_multiple_branches(self):
        org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        branch_1 = Branch.objects.create(organization=org, name="Филиал 1")
        branch_2 = Branch.objects.create(organization=org, name="Филиал 2")

        manager = User.objects.create_user(
            phone="+77010000010",
            full_name="Manager",
            password="pass12345",
            organization=org,
            role=User.Role.MANAGER,
        )
        manager.branches.set([branch_1, branch_2])

        self.assertEqual(manager.branches.count(), 2)

    def test_password_is_stored_as_hash_not_plaintext(self):
        org = Organization.objects.create(name="True Ballet", slug="true-ballet")

        user = User.objects.create_user(
            phone="+77010000011", full_name="Teacher", password="pass12345", organization=org
        )

        self.assertNotEqual(user.password, "pass12345")
        self.assertTrue(user.check_password("pass12345"))

    def test_soft_deleted_user_hidden_from_default_manager(self):
        org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        user = User.objects.create_user(
            phone="+77010000012", full_name="Teacher", password="pass12345", organization=org
        )

        user.delete()

        self.assertFalse(User.objects.filter(pk=user.pk).exists())


@tag("tenant_isolation")
class UserAPITests(APITestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.org_b = Organization.objects.create(name="Другая студия", slug="another-studio")
        self.branch_a = Branch.objects.create(organization=self.org_a, name="Филиал A")
        self.branch_b = Branch.objects.create(organization=self.org_b, name="Филиал B")

        self.owner_a = User.objects.create_user(
            phone="+77010000001",
            full_name="Owner A",
            password="pass12345",
            organization=self.org_a,
            role=User.Role.OWNER,
        )
        self.owner_b = User.objects.create_user(
            phone="+77010000002",
            full_name="Owner B",
            password="pass12345",
            organization=self.org_b,
            role=User.Role.OWNER,
        )

    def test_create_user_attaches_to_own_branches_and_organization(self):
        self.client.force_authenticate(self.owner_a)

        response = self.client.post(
            "/api/v1/users/",
            {
                "phone": "+77010000020",
                "full_name": "Teacher One",
                "password": "pass12345",
                "role": User.Role.TEACHER,
                "branches": [str(self.branch_a.id)],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created = User.objects.get(pk=response.data["id"])
        self.assertEqual(created.organization_id, self.org_a.id)
        self.assertEqual(list(created.branches.values_list("id", flat=True)), [self.branch_a.id])
        self.assertTrue(created.check_password("pass12345"))

    def test_cannot_attach_new_user_to_another_organizations_branch(self):
        self.client.force_authenticate(self.owner_a)

        response = self.client.post(
            "/api/v1/users/",
            {
                "phone": "+77010000021",
                "full_name": "Teacher Two",
                "password": "pass12345",
                "branches": [str(self.branch_b.id)],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("branches", response.data)

    def test_user_list_is_scoped_to_own_organization(self):
        self.client.force_authenticate(self.owner_a)

        response = self.client.get("/api/v1/users/")

        phones = [u["phone"] for u in response.data["results"]]
        self.assertEqual(phones, ["+77010000001"])


class AuthTests(TestCase):
    def setUp(self):
        cache.clear()  # лимит запросов на логин считается в кэше — не тянуть его между тестами
        self.client = APIClient()
        self.org = Organization.objects.create(name="Балет Астана", slug="ballet-astana")
        self.owner = User.objects.create_user(
            phone="77001234567",
            password="StrongPass123!",
            full_name="Владелец",
            organization=self.org,
            role=User.Role.OWNER,
        )

    def test_register_organization(self):
        response = self.client.post(
            "/api/v1/users/auth/register/",
            {
                "org_name": "Новая школа",
                "org_slug": "new-school",
                "full_name": "Директор",
                "phone": "77009999999",
                "password": "StrongPass123!",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_login_returns_tokens(self):
        response = self.client.post(
            "/api/v1/users/auth/login/",
            {"phone": "77001234567", "password": "StrongPass123!"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_stale_token_of_disabled_user_does_not_block_login(self):
        """В браузере остался токен пользователя, которого потом отключили:
        вход и регистрация должны работать, остальные запросы — 401, не 500."""
        gone = User.objects.create_user(
            phone="77005550000", password="x", full_name="Бывший", organization=self.org
        )
        stale = str(RefreshToken.for_user(gone).access_token)
        User.objects.filter(pk=gone.pk).update(is_active=False)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {stale}")
        login = self.client.post(
            "/api/v1/users/auth/login/", {"phone": "77001234567", "password": "StrongPass123!"}
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        register = self.client.post(
            "/api/v1/users/auth/register/",
            {
                "org_name": "Ещё школа",
                "org_slug": "one-more-school",
                "full_name": "Директор",
                "phone": "77008888888",
                "password": "StrongPass123!",
            },
        )
        self.assertEqual(register.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.client.get("/api/v1/users/auth/me/").status_code, 401)

    def test_login_normalizes_formatted_phone(self):
        response = self.client.post(
            "/api/v1/users/auth/login/",
            {"phone": "+7 (700) 123-45-67", "password": "StrongPass123!"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)

    def test_register_rejects_invalid_person_name(self):
        response = self.client.post(
            "/api/v1/users/auth/register/",
            {
                "org_name": "Новая школа",
                "full_name": "А1",
                "phone": "77009999998",
                "password": "StrongPass123!",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("full_name", response.data)

    def test_login_accepts_legacy_pbkdf2_password_and_upgrades_hash(self):
        self.owner.password = make_password("StrongPass123!", hasher="pbkdf2_sha256")
        self.owner.save(update_fields=["password"])

        response = self.client.post(
            "/api/v1/users/auth/login/",
            {"phone": "77001234567", "password": "StrongPass123!"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.password.startswith("argon2"))

    def _login(self):
        return self.client.post(
            "/api/v1/users/auth/login/",
            {"phone": "77001234567", "password": "StrongPass123!"},
        ).data

    def test_refresh_gives_access_that_still_carries_organization(self):
        # frontend2 продлевает access по refresh (TRU-79) — новый access
        # должен работать на эндпоинтах организации так же, как после входа.
        tokens = self._login()

        response = self.client.post("/api/v1/users/auth/refresh/", {"refresh": tokens["refresh"]})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        me = self.client.get("/api/v1/organization/")
        self.assertEqual(me.status_code, status.HTTP_200_OK)
        self.assertEqual(str(me.data["id"]), str(self.org.id))

    def test_used_refresh_token_is_rejected_after_rotation(self):
        tokens = self._login()
        first = self.client.post("/api/v1/users/auth/refresh/", {"refresh": tokens["refresh"]})
        self.assertIn("refresh", first.data)  # ротация — выдан новый refresh

        again = self.client.post("/api/v1/users/auth/refresh/", {"refresh": tokens["refresh"]})

        self.assertEqual(again.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_wrong_password_does_not_reveal_user_existence(self):
        response = self.client.post(
            "/api/v1/users/auth/login/",
            {"phone": "77001234567", "password": "WrongPass"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn("77001234567", str(response.data))

    def test_logout_blacklists_token(self):
        refresh = RefreshToken.for_user(self.owner)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")
        response = self.client.post(
            "/api/v1/users/auth/logout/",
            {"refresh": str(refresh)},
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_invite_staff(self):
        refresh = RefreshToken.for_user(self.owner)
        refresh["organization_id"] = str(self.org.id)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")
        response = self.client.post(
            "/api/v1/users/auth/invite/",
            {
                "full_name": "Администратор",
                "phone": "77007777777",
                "role": "admin",
                "password": "StrongPass123!",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["role"], "admin")

    def test_change_password(self):
        refresh = RefreshToken.for_user(self.owner)
        refresh["organization_id"] = str(self.org.id)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")
        response = self.client.post(
            "/api/v1/users/auth/change-password/",
            {
                "old_password": "StrongPass123!",
                "new_password": "NewStrongPass456!",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_change_password_wrong_old(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            "/api/v1/users/auth/change-password/",
            {"old_password": "Nope", "new_password": "NewStrongPass456!"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("old_password", response.data)

    def test_change_password_rejects_password_like_name(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            "/api/v1/users/auth/change-password/",
            {"old_password": "StrongPass123!", "new_password": "77001234567"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("new_password", response.data)

    def test_profile_updates_own_name(self):
        self.client.force_authenticate(self.owner)
        response = self.client.patch(
            "/api/v1/users/auth/me/", {"full_name": "  Сауле   Бекмуханова "}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["full_name"], "Сауле Бекмуханова")
        self.assertIn("permissions", response.data)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.full_name, "Сауле Бекмуханова")

    def test_profile_cannot_change_phone_or_role(self):
        teacher = User.objects.create_user(
            phone="77005550000",
            password="StrongPass123!",
            full_name="Педагог",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        self.client.force_authenticate(teacher)
        response = self.client.patch(
            "/api/v1/users/auth/me/",
            {"full_name": "Жанна Абенова", "phone": "77009999999", "role": "owner"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        teacher.refresh_from_db()
        self.assertEqual(teacher.phone, "77005550000")
        self.assertEqual(teacher.role, User.Role.TEACHER)
        self.assertEqual(teacher.full_name, "Жанна Абенова")

    def test_profile_rejects_bad_name(self):
        self.client.force_authenticate(self.owner)
        for bad in ["", "А", "Admin123"]:
            response = self.client.patch(
                "/api/v1/users/auth/me/", {"full_name": bad}, format="json"
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, bad)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.full_name, "Владелец")

    def test_profile_requires_login(self):
        response = self.client.patch(
            "/api/v1/users/auth/me/", {"full_name": "Кто-то"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_password_not_stored_in_plain_text(self):
        self.assertNotEqual(self.owner.password, "StrongPass123!")
        self.assertTrue(self.owner.password.startswith("argon2"))

    def test_rate_limit_on_login(self):
        for _ in range(6):
            response = self.client.post(
                "/api/v1/users/auth/login/",
                {"phone": "77001234567", "password": "WrongPass"},
            )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


def _png(name="me.png", size=(20, 20)):
    buffer = io.BytesIO()
    Image.new("RGB", size, (228, 88, 110)).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class ProfilePhotoTests(APITestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        org = Organization.objects.create(name="Балет Астана", slug="ballet-astana")
        self.user = User.objects.create_user(
            phone="77001234567",
            password="StrongPass123!",
            full_name="Айнур Касымова",
            organization=org,
            role=User.Role.ADMIN,
        )
        self.client.force_authenticate(self.user)

    def upload(self, file):
        return self.client.post("/api/v1/users/auth/me/photo/", {"file": file}, format="multipart")

    def stored_files(self):
        folder = Path(self.media) / "users" / "photos"
        return sorted(p.name for p in folder.iterdir()) if folder.exists() else []

    def test_upload_sets_photo(self):
        response = self.upload(_png())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("/media/users/photos/", response.data["photo_url"])
        self.user.refresh_from_db()
        self.assertEqual(self.user.photo_url, response.data["photo_url"])
        self.assertEqual(len(self.stored_files()), 1)

    def test_replace_removes_old_file(self):
        first = self.upload(_png()).data["photo_url"]
        second = self.upload(_png("second.png")).data["photo_url"]
        self.assertNotEqual(first, second)
        self.assertEqual(self.stored_files(), [second.rsplit("/", 1)[1]])

    def test_delete_clears_photo_and_file(self):
        self.upload(_png())
        response = self.client.delete("/api/v1/users/auth/me/photo/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["photo_url"], "")
        self.assertEqual(self.stored_files(), [])

    def test_rejects_not_image(self):
        fake = SimpleUploadedFile("me.png", b"not an image", content_type="image/png")
        response = self.upload(fake)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("file", response.data)
        self.assertEqual(self.stored_files(), [])

    def test_rejects_too_big(self):
        big = SimpleUploadedFile("big.png", b"0" * (5 * 1024 * 1024 + 1), content_type="image/png")
        response = self.upload(big)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["file"], ["Файл больше 5 МБ."])

    def test_foreign_url_is_not_deleted(self):
        self.user.photo_url = "https://example.com/media/users/photos/x.png"
        self.user.save()
        response = self.client.delete("/api/v1/users/auth/me/photo/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_requires_login(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.upload(_png()).status_code, status.HTTP_401_UNAUTHORIZED)
