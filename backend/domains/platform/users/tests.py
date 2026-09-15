from django.test import tag
from rest_framework import status
from rest_framework.test import APITestCase

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
