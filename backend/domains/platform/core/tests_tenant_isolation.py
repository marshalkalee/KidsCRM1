from django.test import TestCase, tag
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from domains.platform.tenants.models import Branch, Organization, Room
from domains.platform.users.models import User


def make_token(user):
    refresh = RefreshToken.for_user(user)
    refresh["organization_id"] = str(user.organization_id)
    return str(refresh.access_token)


@tag("tenant_isolation")
class TenantIsolationTest(TestCase):
    def setUp(self):
        self.client_a = APIClient()
        self.client_b = APIClient()

        self.org_a = Organization.objects.create(name="Балет Астана", slug="ballet-astana")
        self.user_a = User.objects.create_user(
            phone="77001111111",
            password="pass",
            full_name="Админ А",
            organization=self.org_a,
            role=User.Role.ADMIN,
        )
        self.branch_a = Branch.objects.create(
            name="Филиал А",
            organization=self.org_a,
        )
        self.room_a = Room.objects.create(
            name="Зал А",
            organization=self.org_a,
            branch=self.branch_a,
        )

        self.org_b = Organization.objects.create(name="Школа танцев", slug="shkola-tantsev")
        self.user_b = User.objects.create_user(
            phone="77002222222",
            password="pass",
            full_name="Админ Б",
            organization=self.org_b,
            role=User.Role.ADMIN,
        )
        self.branch_b = Branch.objects.create(
            name="Филиал Б",
            organization=self.org_b,
        )
        self.room_b = Room.objects.create(
            name="Зал Б",
            organization=self.org_b,
            branch=self.branch_b,
        )

        self.client_a.credentials(HTTP_AUTHORIZATION=f"Bearer {make_token(self.user_a)}")
        self.client_b.credentials(HTTP_AUTHORIZATION=f"Bearer {make_token(self.user_b)}")

    def test_org_a_cannot_read_branches_of_org_b(self):
        response = self.client_a.get("/api/v1/branches/")
        self.assertEqual(response.status_code, 200)
        names = [b["name"] for b in response.data["results"]]
        self.assertNotIn("Филиал Б", names)
        self.assertIn("Филиал А", names)

    def test_org_a_cannot_read_branch_of_org_b_by_id(self):
        response = self.client_a.get(f"/api/v1/branches/{self.branch_b.id}/")
        self.assertEqual(response.status_code, 404)

    def test_org_a_cannot_read_rooms_of_org_b(self):
        response = self.client_a.get("/api/v1/rooms/")
        self.assertEqual(response.status_code, 200)
        names = [r["name"] for r in response.data["results"]]
        self.assertNotIn("Зал Б", names)

    def test_org_a_cannot_update_branch_of_org_b(self):
        response = self.client_a.patch(
            f"/api/v1/branches/{self.branch_b.id}/",
            {"name": "Взломанный филиал"},
        )
        self.assertEqual(response.status_code, 404)
        self.branch_b.refresh_from_db()
        self.assertEqual(self.branch_b.name, "Филиал Б")

    def test_org_a_cannot_delete_branch_of_org_b(self):
        response = self.client_a.delete(f"/api/v1/branches/{self.branch_b.id}/")
        self.assertEqual(response.status_code, 404)
        self.branch_b.refresh_from_db()
        self.assertIsNone(self.branch_b.deleted_at)

    def test_cannot_create_branch_in_foreign_org(self):
        response = self.client_a.post(
            "/api/v1/branches/",
            {"name": "Чужой филиал", "organization": str(self.org_b.id)},
        )
        if response.status_code == 201:
            created_id = response.data["id"]
            branch = Branch.objects.get(id=created_id)
            self.assertEqual(branch.organization, self.org_a)

    def test_error_message_does_not_leak_foreign_data(self):
        response = self.client_a.get(f"/api/v1/branches/{self.branch_b.id}/")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("Филиал Б", str(response.data))
