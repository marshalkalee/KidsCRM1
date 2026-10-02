"""
Изоляция тенантов на API — те проверки, что раньше стояли на серверных
страницах (TRU-88 удалил их вместе со страницами): чужое не видно в
списках, его нельзя изменить, удалить или архивировать.
"""

from datetime import date

from django.test import TestCase, tag
from rest_framework.test import APIClient

from domains.people.clients.models import Child, ParentContact
from domains.platform.tenants.models import Direction, Organization
from domains.platform.users.models import User


@tag("tenant_isolation")
class ApiTenantIsolationTests(TestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name="Центр А", slug="iso-a")
        self.org_b = Organization.objects.create(name="Центр Б", slug="iso-b")
        owner = User.objects.create_user(
            phone="+77011110001",
            password="x",
            full_name="Владелец А",
            organization=self.org_a,
            role=User.Role.OWNER,
        )
        self.child_b = Child.objects.create(
            organization=self.org_b, full_name="Чужой Ребёнок", birth_date=date(2018, 1, 1)
        )
        self.parent_b = ParentContact.objects.create(
            organization=self.org_b, full_name="Чужой Родитель"
        )
        self.direction_b = Direction.objects.create(
            organization=self.org_b, name="Чужое направление"
        )
        self.client = APIClient()
        self.client.force_authenticate(owner)

    def ids(self, url):
        data = self.client.get(url).json()
        rows = data.get("results", data) if isinstance(data, dict) else data
        return {str(row["id"]) for row in rows}

    def test_lists_do_not_leak(self):
        self.assertNotIn(str(self.child_b.pk), self.ids("/api/v1/clients/children/"))
        self.assertNotIn(str(self.child_b.pk), self.ids("/api/v1/clients/children/table/"))
        self.assertNotIn(str(self.parent_b.pk), self.ids("/api/v1/clients/parents/"))
        self.assertNotIn(str(self.direction_b.pk), self.ids("/api/v1/directions/"))

    def test_cannot_change_or_delete_foreign_records(self):
        cases = [
            ("patch", f"/api/v1/clients/children/{self.child_b.pk}/", {"full_name": "Взлом"}),
            ("patch", f"/api/v1/clients/parents/{self.parent_b.pk}/", {"full_name": "Взлом"}),
            ("delete", f"/api/v1/clients/parents/{self.parent_b.pk}/", None),
            ("patch", f"/api/v1/directions/{self.direction_b.pk}/", {"name": "Взлом"}),
            ("delete", f"/api/v1/directions/{self.direction_b.pk}/", None),
        ]
        for method, url, body in cases:
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, body, format="json")
                self.assertEqual(response.status_code, 404)
        self.child_b.refresh_from_db()
        self.parent_b.refresh_from_db()
        self.direction_b.refresh_from_db()
        self.assertEqual(self.child_b.full_name, "Чужой Ребёнок")
        self.assertEqual(self.parent_b.full_name, "Чужой Родитель")
        self.assertIsNone(self.parent_b.deleted_at)
        self.assertEqual(self.direction_b.name, "Чужое направление")
        self.assertTrue(self.direction_b.is_active)
