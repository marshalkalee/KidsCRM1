"""
Ребёнок: модель, миграция, API (ТЗ п. 3.1, п. 10.3). Критерии приёмки:
- создаётся, редактируется, переводится между статусами;
- перевод в «ушёл» без причины отклоняется API, а не только формой;
- возраст считается на лету и корректен в день рождения;
- преподаватель видит ребёнка, но не административные поля (leave_reason,
  consent_given) — стык с RBAC;
- изоляция между организациями (тег tenant_isolation).
"""

import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase, tag
from rest_framework import status
from rest_framework.test import APITestCase

from domains.platform.tenants.models import Direction, Organization

from .models import Child

User = get_user_model()


def _today_minus_years(years, day_offset=0):
    today = datetime.date.today()
    try:
        return today.replace(year=today.year - years) + datetime.timedelta(days=day_offset)
    except ValueError:
        # 29 февраля на невисокосный год.
        return today.replace(year=today.year - years, day=28) + datetime.timedelta(days=day_offset)


class ChildModelTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")

    def test_age_is_computed_not_stored(self):
        birth_date = _today_minus_years(7)
        child = Child.objects.create(
            organization=self.org,
            full_name="Аружан",
            birth_date=birth_date,
            gender=Child.Gender.FEMALE,
        )
        self.assertEqual(child.age, 7)
        self.assertNotIn("age", [f.name for f in Child._meta.get_fields()])

    def test_age_is_correct_on_birthday_itself(self):
        birth_date = _today_minus_years(10, day_offset=0)
        child = Child.objects.create(
            organization=self.org,
            full_name="Данияр",
            birth_date=birth_date,
            gender=Child.Gender.MALE,
        )
        self.assertEqual(child.age, 10)

    def test_age_not_yet_incremented_day_before_birthday(self):
        birth_date = _today_minus_years(10, day_offset=1)
        child = Child.objects.create(
            organization=self.org,
            full_name="Данияр",
            birth_date=birth_date,
            gender=Child.Gender.MALE,
        )
        self.assertEqual(child.age, 9)

    def test_soft_delete_hides_from_default_manager_but_keeps_row(self):
        child = Child.objects.create(
            organization=self.org,
            full_name="Аружан",
            birth_date=_today_minus_years(7),
            gender=Child.Gender.FEMALE,
        )

        child.delete()

        self.assertFalse(Child.objects.filter(pk=child.pk).exists())
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT deleted_at FROM clients_child WHERE id = %s", [str(child.pk)])
            row = cursor.fetchone()
        self.assertIsNotNone(row[0])


class ChildAPITests(APITestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.direction = Direction.objects.create(organization=self.org, name="Балет")
        self.owner = User.objects.create_user(
            phone="+77010000001",
            full_name="Owner",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.teacher = User.objects.create_user(
            phone="+77010000002",
            full_name="Teacher",
            password="pass12345",
            organization=self.org,
            role=User.Role.TEACHER,
        )

    def test_owner_creates_child(self):
        self.client.force_authenticate(self.owner)

        response = self.client.post(
            "/api/v1/clients/children/",
            {
                "full_name": "Аружан Касымова",
                "birth_date": str(_today_minus_years(7)),
                "gender": Child.Gender.FEMALE,
                "directions": [str(self.direction.id)],
                "consent_given": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        child = Child.objects.get(pk=response.data["id"])
        self.assertEqual(child.organization_id, self.org.id)
        self.assertEqual(response.data["age"], 7)

    def test_birth_date_in_future_is_rejected(self):
        self.client.force_authenticate(self.owner)

        response = self.client.post(
            "/api/v1/clients/children/",
            {
                "full_name": "Аружан",
                "birth_date": str(datetime.date.today() + datetime.timedelta(days=1)),
                "gender": Child.Gender.FEMALE,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("birth_date", response.data)

    def test_transition_to_left_without_reason_is_rejected(self):
        self.client.force_authenticate(self.owner)
        child = Child.objects.create(
            organization=self.org,
            full_name="Аружан",
            birth_date=_today_minus_years(7),
            gender=Child.Gender.FEMALE,
        )

        response = self.client.patch(
            f"/api/v1/clients/children/{child.id}/", {"status": "left"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("leave_reason", response.data)
        child.refresh_from_db()
        self.assertEqual(child.status, Child.Status.ACTIVE)

    def test_transition_to_left_with_reason_is_accepted(self):
        self.client.force_authenticate(self.owner)
        child = Child.objects.create(
            organization=self.org,
            full_name="Аружан",
            birth_date=_today_minus_years(7),
            gender=Child.Gender.FEMALE,
        )

        response = self.client.patch(
            f"/api/v1/clients/children/{child.id}/",
            {"status": "left", "leave_reason": "Переезд в другой город"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        child.refresh_from_db()
        self.assertEqual(child.status, Child.Status.LEFT)

    def test_disallowed_status_transition_is_rejected(self):
        self.client.force_authenticate(self.owner)
        child = Child.objects.create(
            organization=self.org,
            full_name="Аружан",
            birth_date=_today_minus_years(7),
            gender=Child.Gender.FEMALE,
            status=Child.Status.LEFT,
            leave_reason="Переезд",
        )

        # LEFT -> PAUSED не входит в допустимые переходы.
        response = self.client.patch(
            f"/api/v1/clients/children/{child.id}/", {"status": "paused"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("status", response.data)

    def test_teacher_can_view_child_but_not_sensitive_fields(self):
        child = Child.objects.create(
            organization=self.org,
            full_name="Аружан",
            birth_date=_today_minus_years(7),
            gender=Child.Gender.FEMALE,
            status=Child.Status.LEFT,
            leave_reason="Переезд",
            consent_given=True,
        )
        self.client.force_authenticate(self.teacher)

        response = self.client.get(f"/api/v1/clients/children/{child.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["full_name"], "Аружан")
        self.assertNotIn("leave_reason", response.data)
        self.assertNotIn("consent_given", response.data)

    def test_owner_sees_sensitive_fields(self):
        child = Child.objects.create(
            organization=self.org,
            full_name="Аружан",
            birth_date=_today_minus_years(7),
            gender=Child.Gender.FEMALE,
            status=Child.Status.LEFT,
            leave_reason="Переезд",
        )
        self.client.force_authenticate(self.owner)

        response = self.client.get(f"/api/v1/clients/children/{child.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["leave_reason"], "Переезд")

    def test_teacher_cannot_create_child(self):
        self.client.force_authenticate(self.teacher)

        response = self.client.post(
            "/api/v1/clients/children/",
            {
                "full_name": "Аружан",
                "birth_date": str(_today_minus_years(7)),
                "gender": Child.Gender.FEMALE,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_no_iin_field_on_child(self):
        field_names = [f.name for f in Child._meta.get_fields()]
        self.assertNotIn("iin", field_names)


@tag("tenant_isolation")
class ChildTenantIsolationTests(APITestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.org_b = Organization.objects.create(name="Другая студия", slug="another-studio")
        self.direction_b = Direction.objects.create(organization=self.org_b, name="Балет Б")
        self.child_b = Child.objects.create(
            organization=self.org_b,
            full_name="Чужой ребёнок",
            birth_date=_today_minus_years(6),
            gender=Child.Gender.MALE,
        )
        self.owner_a = User.objects.create_user(
            phone="+77010000001",
            full_name="Owner A",
            password="pass12345",
            organization=self.org_a,
            role=User.Role.OWNER,
        )
        self.client.force_authenticate(self.owner_a)

    def test_child_list_is_scoped_to_own_organization(self):
        response = self.client.get("/api/v1/clients/children/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [c["full_name"] for c in response.data["results"]]
        self.assertEqual(names, [])

    def test_cannot_retrieve_another_organizations_child(self):
        response = self.client.get(f"/api/v1/clients/children/{self.child_b.id}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_attach_child_to_another_organizations_direction(self):
        response = self.client.post(
            "/api/v1/clients/children/",
            {
                "full_name": "Новый ребёнок",
                "birth_date": str(_today_minus_years(7)),
                "gender": Child.Gender.FEMALE,
                "directions": [str(self.direction_b.id)],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("directions", response.data)
