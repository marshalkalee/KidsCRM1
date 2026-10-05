import datetime

from django.utils import timezone
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from domains.people.clients.models import Child
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.schedule.models import Lesson

from .models import Attendance, ParentNote
from .parent_notes import parent_notes_for_child


def authenticated_client(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    refresh["organization_id"] = str(user.organization_id)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


class ParentNoteApiTests(APITestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Центр", slug="notes-centre")
        branch = Branch.objects.create(organization=self.organization, name="Главный")
        direction = Direction.objects.create(organization=self.organization, name="Балет")
        self.teacher = User.objects.create_user(
            phone="+77000000471",
            password="test",
            full_name="Анна Педагог",
            organization=self.organization,
            role=User.Role.TEACHER,
        )
        self.other_teacher = User.objects.create_user(
            phone="+77000000472",
            password="test",
            full_name="Другой педагог",
            organization=self.organization,
            role=User.Role.TEACHER,
        )
        self.group = Group.objects.create(
            organization=self.organization,
            branch=branch,
            direction=direction,
            name="Балет 8–10",
            capacity=10,
        )
        self.children = [
            Child.objects.create(
                organization=self.organization,
                full_name=name,
                birth_date=datetime.date(2017, 1, 1),
                medical_notes="Внутренняя медицинская информация" if index == 0 else "",
            )
            for index, name in enumerate(("Алина", "Милана"))
        ]
        for child in self.children:
            GroupMembership.objects.create(
                organization=self.organization,
                group=self.group,
                child=child,
                joined_at=timezone.localdate(),
            )
        starts_at = timezone.now() - datetime.timedelta(hours=1)
        self.lesson = Lesson.objects.create(
            organization=self.organization,
            group=self.group,
            teacher=self.teacher,
            starts_at=starts_at,
            ends_at=starts_at + datetime.timedelta(hours=1),
        )
        Attendance.objects.create(
            organization=self.organization,
            lesson=self.lesson,
            child=self.children[0],
            status=Attendance.Status.PRESENT,
            marked_by=self.teacher,
            marked_at=timezone.now(),
        )
        self.url = "/api/v1/attendance/parent-notes/"
        self.client = authenticated_client(self.teacher)

    def test_teacher_creates_group_and_child_notes_from_lesson(self):
        group_response = self.client.post(
            self.url,
            {"lesson": str(self.lesson.id), "scope": "group", "body": "Принести форму"},
            format="json",
        )
        child_response = self.client.post(
            self.url,
            {
                "lesson": str(self.lesson.id),
                "scope": "child",
                "child": str(self.children[0].id),
                "body": "Поработать над осанкой",
            },
            format="json",
        )

        self.assertEqual(group_response.status_code, 201, group_response.data)
        self.assertEqual(child_response.status_code, 201, child_response.data)
        self.assertTrue(group_response.data["can_edit"])
        self.assertEqual(child_response.data["child_name"], "Алина")

    def test_group_note_reaches_group_and_child_note_only_target_child(self):
        group_note = ParentNote.objects.create(
            organization=self.organization,
            lesson=self.lesson,
            scope=ParentNote.Scope.GROUP,
            author=self.teacher,
            body="Всем принести форму",
        )
        child_note = ParentNote.objects.create(
            organization=self.organization,
            lesson=self.lesson,
            scope=ParentNote.Scope.CHILD,
            child=self.children[0],
            author=self.teacher,
            body="Алине повторить комбинацию",
        )

        self.assertSetEqual(
            set(parent_notes_for_child(self.children[0]).values_list("id", flat=True)),
            {group_note.id, child_note.id},
        )
        self.assertSetEqual(
            set(parent_notes_for_child(self.children[1]).values_list("id", flat=True)),
            {group_note.id},
        )

    def test_internal_medical_notes_are_never_serialized(self):
        response = self.client.post(
            self.url,
            {
                "lesson": str(self.lesson.id),
                "scope": "child",
                "child": str(self.children[0].id),
                "body": "Упражнение для дома",
            },
            format="json",
        )

        self.assertNotIn("medical_notes", response.data)
        self.assertNotIn("Внутренняя медицинская информация", str(response.data))

    def test_templates_and_author_only_editing(self):
        created = self.client.post(
            self.url,
            {"lesson": str(self.lesson.id), "scope": "group", "body": "Старый текст"},
            format="json",
        )
        note_url = f"/api/v1/attendance/parent-notes/{created.data['id']}/"
        templates = self.client.get(self.url, {"lesson": str(self.lesson.id)})
        self.assertGreaterEqual(len(templates.data["templates"]), 3)

        self.client = authenticated_client(self.other_teacher)
        denied = self.client.patch(note_url, {"body": "Чужая правка"}, format="json")
        self.assertEqual(denied.status_code, 403)

        self.client = authenticated_client(self.teacher)
        updated = self.client.patch(note_url, {"body": "Новый текст"}, format="json")
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data["body"], "Новый текст")

        ParentNote.objects.filter(pk=created.data["id"]).update(
            created_at=timezone.now() - datetime.timedelta(hours=25)
        )
        expired = self.client.patch(note_url, {"body": "Слишком поздно"}, format="json")
        self.assertEqual(expired.status_code, 403)

    def test_note_can_be_created_before_attendance_is_marked(self):
        other_lesson = Lesson.objects.create(
            organization=self.organization,
            group=self.group,
            teacher=self.teacher,
            starts_at=timezone.now(),
            ends_at=timezone.now() + datetime.timedelta(hours=1),
        )
        response = self.client.post(
            self.url,
            {"lesson": str(other_lesson.id), "scope": "group", "body": "Задание"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
