from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from domains.platform.tenants.models import Branch, Organization
from domains.platform.users.models import User


def make_client(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    refresh["organization_id"] = str(user.organization_id)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")
    return client


class RBACTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Балет Астана", slug="ballet-astana")
        self.branch = Branch.objects.create(name="Центральный", organization=self.org)

        self.owner = User.objects.create_user(
            phone="77000000001",
            password="pass",
            full_name="Владелец",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.manager = User.objects.create_user(
            phone="77000000002",
            password="pass",
            full_name="Управляющий",
            organization=self.org,
            role=User.Role.MANAGER,
        )
        self.admin = User.objects.create_user(
            phone="77000000003",
            password="pass",
            full_name="Администратор",
            organization=self.org,
            role=User.Role.ADMIN,
        )
        self.teacher = User.objects.create_user(
            phone="77000000004",
            password="pass",
            full_name="Преподаватель",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        self.accountant = User.objects.create_user(
            phone="77000000005",
            password="pass",
            full_name="Бухгалтер",
            organization=self.org,
            role=User.Role.ACCOUNTANT,
        )

    def test_owner_can_access_me(self):
        client = make_client(self.owner)
        response = client.get("/api/v1/users/auth/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["permissions"]["can_view_financials"])
        self.assertTrue(response.data["permissions"]["can_view_org_summary"])

    def test_teacher_cannot_view_financials(self):
        client = make_client(self.teacher)
        response = client.get("/api/v1/users/auth/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["permissions"]["can_view_financials"])

    def test_admin_cannot_view_org_summary(self):
        client = make_client(self.admin)
        response = client.get("/api/v1/users/auth/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["permissions"]["can_view_org_summary"])

    def test_accountant_cannot_edit_schedule(self):
        client = make_client(self.accountant)
        response = client.get("/api/v1/users/auth/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["permissions"]["can_edit_schedule"])

    def test_can_manage_children_flag(self):
        for user, expected in [
            (self.owner, True),
            (self.manager, True),
            (self.admin, True),
            (self.teacher, False),
            (self.accountant, False),
        ]:
            response = make_client(user).get("/api/v1/users/auth/me/")
            self.assertEqual(response.data["permissions"]["can_manage_children"], expected)

    def test_unauthenticated_request_is_rejected(self):
        client = APIClient()
        response = client.get("/api/v1/users/auth/me/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_manager_can_manage_staff(self):
        client = make_client(self.manager)
        response = client.get("/api/v1/users/auth/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["permissions"]["can_manage_staff"])

    def test_teacher_cannot_manage_staff(self):
        client = make_client(self.teacher)
        response = client.get("/api/v1/users/auth/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["permissions"]["can_manage_staff"])

    def test_manager_sees_only_own_branches(self):
        branch2 = Branch.objects.create(name="Второй филиал", organization=self.org)
        self.manager.branches.add(self.branch)

        client = make_client(self.manager)
        response = client.get("/api/v1/users/auth/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        branch_ids = response.data["branches"]
        self.assertIn(str(self.branch.id), branch_ids)
        self.assertNotIn(str(branch2.id), branch_ids)

    def test_owner_sees_all_branches(self):
        Branch.objects.create(name="Второй филиал", organization=self.org)
        client = make_client(self.owner)
        response = client.get("/api/v1/branches/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)

    def test_teacher_cannot_create_branch(self):
        client = make_client(self.teacher)
        response = client.post("/api/v1/branches/", {"name": "Новый филиал"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_accountant_cannot_create_room(self):
        client = make_client(self.accountant)
        response = client.post(
            "/api/v1/rooms/",
            {"name": "Новый зал", "branch": str(self.branch.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_teacher_can_read_branches(self):
        client = make_client(self.teacher)
        response = client.get("/api/v1/branches/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_admin_cannot_read_organization(self):
        client = make_client(self.admin)
        response = client.get("/api/v1/organization/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_can_read_organization(self):
        client = make_client(self.owner)
        response = client.get("/api/v1/organization/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
