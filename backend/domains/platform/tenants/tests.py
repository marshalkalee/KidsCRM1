from django.contrib.auth import get_user_model
from django.test import tag
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Branch, Organization, Room

User = get_user_model()


class OrganizationBranchRoomModelTests(APITestCase):
    def test_organization_can_have_three_branches_with_rooms(self):
        org = Organization.objects.create(name="True Ballet", slug="true-ballet")

        branches = [
            Branch.objects.create(organization=org, name=f"Филиал {i}") for i in range(1, 4)
        ]
        self.assertEqual(Branch.objects.for_tenant(org).count(), 3)

        for branch in branches:
            Room.objects.create(branch=branch, name="Зал 1")
            Room.objects.create(branch=branch, name="Зал 2")

        self.assertEqual(Room.objects.for_tenant(org).count(), 6)

    def test_room_organization_is_derived_from_branch(self):
        org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        branch = Branch.objects.create(organization=org, name="Центральный")

        room = Room.objects.create(branch=branch, name="Зал 1")

        self.assertEqual(room.organization_id, org.id)

    def test_soft_delete_hides_from_default_manager_but_keeps_row(self):
        org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        branch = Branch.objects.create(organization=org, name="Центральный")

        branch.delete()

        self.assertFalse(Branch.objects.filter(pk=branch.pk).exists())

        # Мягкое удаление — запись физически на месте, просто скрыта менеджером.
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT deleted_at FROM tenants_branch WHERE id = %s", [str(branch.pk)])
            row = cursor.fetchone()
        self.assertIsNotNone(row[0])


@tag("tenant_isolation")
class TenantScopedAPITests(APITestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.org_b = Organization.objects.create(name="Другая студия", slug="another-studio")

        self.branch_a = Branch.objects.create(organization=self.org_a, name="Филиал A")
        self.branch_b = Branch.objects.create(organization=self.org_b, name="Филиал B")

        self.user_a = User.objects.create_user(
            phone="+77010000001",
            full_name="Owner A",
            password="pass12345",
            organization=self.org_a,
            role=User.Role.OWNER,
        )
        self.user_b = User.objects.create_user(
            phone="+77010000002",
            full_name="Owner B",
            password="pass12345",
            organization=self.org_b,
            role=User.Role.OWNER,
        )

    def test_branch_list_is_scoped_to_own_organization(self):
        self.client.force_authenticate(self.user_a)

        response = self.client.get("/api/v1/branches/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [b["name"] for b in response.data["results"]]
        self.assertEqual(names, ["Филиал A"])

    def test_cannot_create_room_in_another_organizations_branch(self):
        self.client.force_authenticate(self.user_a)

        response = self.client.post(
            "/api/v1/rooms/", {"branch": str(self.branch_b.id), "name": "Чужой зал"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("branch", response.data)

    def test_created_branch_is_attached_to_callers_organization(self):
        self.client.force_authenticate(self.user_a)

        response = self.client.post("/api/v1/branches/", {"name": "Новый филиал"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created = Branch.objects.get(pk=response.data["id"])
        self.assertEqual(created.organization_id, self.org_a.id)

    def test_organization_me_returns_only_callers_organization(self):
        self.client.force_authenticate(self.user_a)

        response = self.client.get("/api/v1/organization/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "True Ballet")

    def test_anonymous_request_is_rejected(self):
        response = self.client.get("/api/v1/branches/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class BranchArchiveApiTests(APITestCase):
    """
    Новый фронт (React) заменяет старые серверные страницы настроек
    (branch_list.html и т.п.) — «архивация» филиала должна остаться
    PATCH is_active, а не DELETE (тот убрал бы филиал из for_tenant()
    совсем, см. TimestampedSoftDeleteModel.delete()).
    """

    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.branch = Branch.objects.create(organization=self.org, name="Центральный")
        self.owner = User.objects.create_user(
            phone="+77030000001",
            full_name="Владелец",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )

    def test_patch_is_active_archives_branch_without_soft_deleting_it(self):
        self.client.force_authenticate(self.owner)

        response = self.client.patch(
            f"/api/v1/branches/{self.branch.id}/", {"is_active": False}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["is_active"])
        # Архивный, но не мягко удалённый — for_tenant() его всё ещё видит.
        self.assertTrue(Branch.objects.for_tenant(self.org).filter(pk=self.branch.pk).exists())

    def test_patch_is_active_restores_branch(self):
        self.branch.is_active = False
        self.branch.save(update_fields=["is_active"])
        self.client.force_authenticate(self.owner)

        response = self.client.patch(
            f"/api/v1/branches/{self.branch.id}/", {"is_active": True}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["is_active"])


class DirectionApiTests(APITestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.other_org = Organization.objects.create(name="Другая студия", slug="other")
        self.branch = Branch.objects.create(organization=self.org, name="Центральный")
        self.archived_branch = Branch.objects.create(
            organization=self.org, name="Закрытый", is_active=False
        )
        self.foreign_branch = Branch.objects.create(organization=self.other_org, name="Чужой")
        self.owner = User.objects.create_user(
            phone="+77030000002",
            full_name="Владелец",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )

    def test_create_direction_with_age_range_and_branches(self):
        self.client.force_authenticate(self.owner)

        response = self.client.post(
            "/api/v1/directions/",
            {
                "name": "Балет",
                "color": "#AA00FF",
                "age_min": 4,
                "age_max": 12,
                "branches": [str(self.branch.id)],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["age_min"], 4)
        self.assertEqual(response.data["age_max"], 12)
        self.assertEqual(response.data["branches"], [self.branch.id])

    def test_age_max_below_age_min_is_rejected(self):
        self.client.force_authenticate(self.owner)

        response = self.client.post(
            "/api/v1/directions/",
            {"name": "Балет", "age_min": 10, "age_max": 5},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("age_max", response.data)

    def test_cannot_attach_archived_or_foreign_branch(self):
        self.client.force_authenticate(self.owner)

        response = self.client.post(
            "/api/v1/directions/",
            {"name": "Балет", "branches": [str(self.archived_branch.id)]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("branches", response.data)

        response = self.client.post(
            "/api/v1/directions/",
            {"name": "Балет", "branches": [str(self.foreign_branch.id)]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("branches", response.data)
