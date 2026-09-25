"""
TRU-90: кто может заводить и менять сотрудников. Раньше /api/v1/users/ был
открыт на запись любому сотруднику — преподаватель мог сделать себя
владельцем или сменить владельцу пароль.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from domains.platform.tenants.models import Organization

from .models import User

URL = "/api/v1/users/"


class UserPermissionTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.owner = self.make("+77010000001", User.Role.OWNER)
        self.manager = self.make("+77010000002", User.Role.MANAGER)
        self.teacher = self.make("+77010000003", User.Role.TEACHER)
        self.api = APIClient()

    def make(self, phone, role):
        return User.objects.create_user(
            phone=phone, full_name=role, password="pass12345", organization=self.org, role=role
        )

    def as_(self, user):
        self.api.force_authenticate(user)
        return self.api

    def test_teacher_can_list_but_not_write(self):
        api = self.as_(self.teacher)
        self.assertEqual(api.get(URL).status_code, 200)
        self.assertEqual(
            api.patch(f"{URL}{self.teacher.pk}/", {"role": "owner"}, format="json").status_code,
            403,
        )
        self.assertEqual(
            api.patch(
                f"{URL}{self.owner.pk}/", {"password": "hacked-pass-1"}, format="json"
            ).status_code,
            403,
        )
        self.assertEqual(api.delete(f"{URL}{self.manager.pk}/").status_code, 403)
        self.teacher.refresh_from_db()
        self.assertEqual(self.teacher.role, User.Role.TEACHER)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password("pass12345"))

    def test_manager_cannot_create_or_touch_owner(self):
        api = self.as_(self.manager)
        new_owner = api.post(
            URL,
            {"phone": "+77010000009", "full_name": "X", "role": "owner", "password": "pass12345"},
            format="json",
        )
        edit_owner = api.patch(f"{URL}{self.owner.pk}/", {"full_name": "Y"}, format="json")
        promote_self = api.patch(f"{URL}{self.manager.pk}/", {"role": "owner"}, format="json")

        self.assertEqual(new_owner.status_code, 400)
        self.assertEqual(edit_owner.status_code, 400)
        self.assertEqual(promote_self.status_code, 400)

    def test_manager_can_create_teacher(self):
        response = self.as_(self.manager).post(
            URL,
            {"phone": "+77010000010", "full_name": "T", "role": "teacher", "password": "pass12345"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)

    def test_nobody_changes_own_role_or_deletes_self(self):
        api = self.as_(self.owner)
        self.assertEqual(
            api.patch(f"{URL}{self.owner.pk}/", {"role": "manager"}, format="json").status_code, 400
        )
        self.assertEqual(api.delete(f"{URL}{self.owner.pk}/").status_code, 400)

    def test_role_filter(self):
        rows = self.as_(self.owner).get(URL, {"role": "teacher"}).json()["results"]
        self.assertEqual([r["id"] for r in rows], [str(self.teacher.pk)])

    def test_invite_requires_owner_or_manager(self):
        invite = "/api/v1/users/auth/invite/"
        payload = {
            "full_name": "Z",
            "phone": "+77010000011",
            "role": "owner",
            "password": "S3cure-pass!",
        }
        teacher = self.as_(self.teacher).post(invite, payload, format="json")
        self.assertEqual(teacher.status_code, 403)
        manager = self.as_(self.manager).post(invite, payload, format="json")
        self.assertEqual(manager.status_code, 400)
