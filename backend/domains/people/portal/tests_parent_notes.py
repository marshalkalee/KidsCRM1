import datetime

from django.utils import timezone

from domains.platform.tenants.models import Branch, Direction
from domains.platform.users.models import User
from domains.scheduling.attendance.models import ParentNote
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.schedule.models import Lesson, LessonEnrollment

from .tests_auth import PortalAuthBase, family


class ParentNotesPortalTests(PortalAuthBase):
    def setUp(self):
        super().setUp()
        branch = Branch.objects.filter(organization=self.org).first()
        direction = Direction.objects.create(organization=self.org, name="Балет")
        self.teacher = User.objects.create_user(
            phone="+77000000148",
            password="x",
            full_name="Алия Жаксибекова",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        self.group = Group.objects.create(
            organization=self.org,
            branch=branch,
            direction=direction,
            name="Балет 8–10",
            capacity=12,
        )
        GroupMembership.objects.create(
            organization=self.org,
            group=self.group,
            child=self.child,
            joined_at=timezone.localdate(),
        )
        starts_at = timezone.now() - datetime.timedelta(hours=2)
        self.lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            teacher=self.teacher,
            starts_at=starts_at,
            ends_at=starts_at + datetime.timedelta(hours=1),
        )
        self.group_note = ParentNote.objects.create(
            organization=self.org,
            lesson=self.lesson,
            author=self.teacher,
            scope=ParentNote.Scope.GROUP,
            kind=ParentNote.Kind.HOMEWORK,
            body="Растяжка каждый день",
            valid_until=timezone.localdate() + datetime.timedelta(days=5),
        )
        self.personal_note = ParentNote.objects.create(
            organization=self.org,
            lesson=self.lesson,
            author=self.teacher,
            scope=ParentNote.Scope.CHILD,
            child=self.child,
            kind=ParentNote.Kind.NOTE,
            body="Хорошо держит осанку",
        )
        self.client = self.as_parent(self.login())
        self.url = f"/api/v1/portal/children/{self.child.id}/notes/"

    def test_feed_combines_group_and_personal_notes_newest_first(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["unread"], 2)
        self.assertEqual(len(response.data["results"]), 2)
        self.assertEqual({row["scope"] for row in response.data["results"]}, {"group", "child"})
        self.assertEqual(response.data["current_homework"]["id"], str(self.group_note.id))
        self.assertEqual(response.data["results"][0]["lesson"]["name"], "Балет 8–10")

    def test_group_note_is_visible_to_child_enrolled_over_group(self):
        _, (guest,) = family(
            self.org,
            "Родитель приглашённого ребёнка",
            "+77010000888",
            "Приглашённый ребёнок",
        )
        LessonEnrollment.objects.create(
            organization=self.org,
            lesson=self.lesson,
            child=guest,
            kind=LessonEnrollment.Kind.MAKEUP,
        )
        guest_client = self.as_parent(self.login("+77010000888"))

        response = guest_client.get(f"/api/v1/portal/children/{guest.id}/notes/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["id"] for row in response.data["results"]],
            [str(self.group_note.id)],
        )

    def test_read_marker_updates_counter(self):
        read_url = f"{self.url}{self.group_note.id}/read/"
        self.assertEqual(self.client.post(read_url).status_code, 204)
        response = self.client.get(self.url)
        self.assertEqual(response.data["unread"], 1)
        self.assertTrue(
            next(r for r in response.data["results"] if r["id"] == str(self.group_note.id))["read"]
        )

    def test_other_child_cannot_see_or_mark_personal_note(self):
        _, (other_child,) = family(self.org, "Другой родитель", "+77010000999", "Другой ребёнок")
        other = self.as_parent(self.login("+77010000999"))
        other_url = f"/api/v1/portal/children/{other_child.id}/notes/"

        self.assertEqual(other.get(other_url).data["results"], [])
        self.assertEqual(other.post(f"{other_url}{self.personal_note.id}/read/").status_code, 404)

    def test_internal_child_notes_are_not_returned(self):
        self.child.medical_notes = "Скрытая медицинская информация"
        self.child.save(update_fields=["medical_notes", "updated_at"])

        response = self.client.get(self.url)
        self.assertNotIn("medical_notes", str(response.data))
        self.assertNotIn("Скрытая медицинская информация", str(response.data))
