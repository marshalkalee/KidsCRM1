import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from domains.people.clients.models import Child, ChildContact, ParentContact
from domains.platform.core.audit import AuditLog
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.scheduling.groups.models import Group, GroupMembership

from .models import Lesson

User = get_user_model()


def authenticated_client(test, user):
    refresh = RefreshToken.for_user(user)
    refresh["organization_id"] = str(user.organization_id)
    test.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")


class TeacherSubstitutionApiTest(APITestCase):
    url = "/api/v1/schedule/lessons/substitute/"

    def setUp(self):
        self.organization = Organization.objects.create(name="Center", slug="center")
        self.branch = Branch.objects.create(organization=self.organization, name="Branch")
        direction = Direction.objects.create(organization=self.organization, name="Ballet")
        self.group = Group.objects.create(
            organization=self.organization,
            branch=self.branch,
            direction=direction,
            name="Group",
            capacity=12,
        )
        self.owner = User.objects.create_user(
            phone="+77010001001",
            full_name="Owner",
            password="test",
            organization=self.organization,
            role=User.Role.OWNER,
        )
        self.original = User.objects.create_user(
            phone="+77010001002",
            full_name="Original teacher",
            password="test",
            organization=self.organization,
            role=User.Role.TEACHER,
        )
        self.substitute = User.objects.create_user(
            phone="+77010001003",
            full_name="Substitute teacher",
            password="test",
            organization=self.organization,
            role=User.Role.TEACHER,
        )
        self.original.branches.add(self.branch)
        self.substitute.branches.add(self.branch)
        start = timezone.now() + datetime.timedelta(days=2)
        self.lessons = [
            Lesson.objects.create(
                organization=self.organization,
                group=self.group,
                teacher=self.original,
                starts_at=start + datetime.timedelta(days=offset),
                ends_at=start + datetime.timedelta(days=offset, hours=1),
            )
            for offset in range(2)
        ]
        authenticated_client(self, self.owner)

    @patch("domains.scheduling.schedule.substitutions.notify")
    def test_assigns_multiple_lessons_and_notifies_parent_once(self, notify):
        parent = ParentContact.objects.create(
            organization=self.organization,
            full_name="Parent",
        )
        for index in range(2):
            child = Child.objects.create(
                organization=self.organization,
                full_name=f"Child {index}",
                birth_date=datetime.date(2018, 1, index + 1),
            )
            GroupMembership.objects.create(
                organization=self.organization,
                group=self.group,
                child=child,
                joined_at=timezone.localdate(),
            )
            ChildContact.objects.create(
                organization=self.organization,
                child=child,
                parent_contact=parent,
                role=ChildContact.Role.MOTHER,
            )

        response = self.client.post(
            self.url,
            {
                "lesson_ids": [str(lesson.id) for lesson in self.lessons],
                "teacher_id": str(self.substitute.id),
                "notify_parents": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        for lesson in self.lessons:
            lesson.refresh_from_db()
            self.assertEqual(lesson.teacher, self.substitute)
            self.assertEqual(lesson.original_teacher, self.original)
            self.assertTrue(lesson.is_modified)
        audit_count = AuditLog.objects.filter(
            object_id__in=[lesson.id for lesson in self.lessons]
        ).count()
        self.assertEqual(audit_count, 2)
        notify.assert_called_once()
        self.assertEqual(notify.call_args.args[0], parent)

        first_result = response.data["results"][0]
        self.assertTrue(first_result["is_substitution"])
        self.assertEqual(first_result["original_teacher_name"], self.original.full_name)

    @patch("domains.scheduling.schedule.substitutions._notify_parents")
    def test_substitute_replaces_original_teacher_schedule(self, _notify):
        self.client.post(
            self.url,
            {
                "lesson_ids": [str(self.lessons[0].id)],
                "teacher_id": str(self.substitute.id),
                "notify_parents": True,
            },
            format="json",
        )

        date_from = self.lessons[0].starts_at.date().isoformat()
        date_to = self.lessons[-1].starts_at.date().isoformat()
        authenticated_client(self, self.original)
        original_response = self.client.get(
            "/api/v1/schedule/", {"date_from": date_from, "date_to": date_to}
        )
        original_ids = {row["id"] for row in original_response.data}

        authenticated_client(self, self.substitute)
        substitute_response = self.client.get(
            "/api/v1/schedule/", {"date_from": date_from, "date_to": date_to}
        )
        substitute_ids = {row["id"] for row in substitute_response.data}

        lesson_id = str(self.lessons[0].id)
        self.assertNotIn(lesson_id, original_ids)
        self.assertIn(lesson_id, substitute_ids)

    def test_delete_restores_original_teacher(self):
        self.client.post(
            self.url,
            {
                "lesson_ids": [str(self.lessons[0].id)],
                "teacher_id": str(self.substitute.id),
                "notify_parents": False,
            },
            format="json",
        )
        response = self.client.delete(
            self.url,
            {"lesson_ids": [str(self.lessons[0].id)]},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.lessons[0].refresh_from_db()
        self.assertEqual(self.lessons[0].teacher, self.original)
        self.assertIsNone(self.lessons[0].original_teacher)
        self.assertTrue(self.lessons[0].is_modified)

    def test_teacher_cannot_assign_substitution(self):
        authenticated_client(self, self.original)
        response = self.client.post(
            self.url,
            {
                "lesson_ids": [str(self.lessons[0].id)],
                "teacher_id": str(self.substitute.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_other_organization_lesson_is_rejected_without_partial_change(self):
        other = Organization.objects.create(name="Other", slug="other")
        other_branch = Branch.objects.create(organization=other, name="Other branch")
        other_direction = Direction.objects.create(organization=other, name="Other direction")
        other_group = Group.objects.create(
            organization=other,
            branch=other_branch,
            direction=other_direction,
            name="Other group",
            capacity=10,
        )
        other_start = timezone.now() + datetime.timedelta(days=3)
        other_lesson = Lesson.objects.create(
            organization=other,
            group=other_group,
            starts_at=other_start,
            ends_at=other_start + datetime.timedelta(hours=1),
        )

        response = self.client.post(
            self.url,
            {
                "lesson_ids": [str(self.lessons[0].id), str(other_lesson.id)],
                "teacher_id": str(self.substitute.id),
                "notify_parents": False,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.lessons[0].refresh_from_db()
        self.assertEqual(self.lessons[0].teacher, self.original)
        self.assertIsNone(self.lessons[0].original_teacher)

    def test_teacher_outside_lesson_branch_is_rejected(self):
        other_branch = Branch.objects.create(organization=self.organization, name="Other branch")
        self.substitute.branches.set([other_branch])
        response = self.client.post(
            self.url,
            {
                "lesson_ids": [str(self.lessons[0].id)],
                "teacher_id": str(self.substitute.id),
                "notify_parents": False,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
