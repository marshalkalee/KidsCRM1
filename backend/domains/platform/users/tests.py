from django.core.cache import cache
from django.test import TestCase, tag
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
                "full_name": "Teacher 1",
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
                "full_name": "Teacher 2",
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
