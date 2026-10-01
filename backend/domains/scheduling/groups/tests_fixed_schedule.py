import datetime

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from domains.platform.tenants.models import Branch, Direction, Organization, Room
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group
from domains.scheduling.schedule.models import Lesson


class GroupFixedScheduleApiTest(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Kids CRM", slug="fixed-schedule")
        self.branch = Branch.objects.create(
            organization=self.organization,
            name="Главный",
        )
        self.other_branch = Branch.objects.create(
            organization=self.organization,
            name="Другой",
        )
        self.direction = Direction.objects.create(
            organization=self.organization,
            name="Балет",
        )
        self.room = Room.objects.create(branch=self.branch, name="Зал 1")
        self.other_room = Room.objects.create(branch=self.other_branch, name="Чужой зал")
        self.teacher = User.objects.create_user(
            phone="+77000000121",
            password="pass",
            full_name="Анна Педагог",
            organization=self.organization,
            role=User.Role.TEACHER,
        )
        self.owner = User.objects.create_user(
            phone="+77000000122",
            password="pass",
            full_name="Владелец",
            organization=self.organization,
            role=User.Role.OWNER,
        )
        self.group = Group.objects.create(
            organization=self.organization,
            branch=self.branch,
            direction=self.direction,
            name="Младшая группа",
            capacity=12,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.url = f"/api/v1/groups/{self.group.id}/fixed-schedule/"
        self.weekday = (timezone.localdate().weekday() + 1) % 7

    def payload(self, **slot_changes):
        slot = {
            "weekday": self.weekday,
            "start_time": "18:00",
            "duration_minutes": 60,
            "room": str(self.room.id),
            "teacher": str(self.teacher.id),
        }
        slot.update(slot_changes)
        return {"generate_weeks_ahead": 8, "slots": [slot]}

    def test_save_generates_future_lessons_and_returns_schedule(self):
        response = self.client.put(self.url, self.payload(), format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertGreater(response.data["generated_count"], 0)
        self.assertEqual(len(response.data["slots"]), 1)
        self.assertEqual(response.data["slots"][0]["room_name"], "Зал 1")
        self.assertTrue(
            Lesson.objects.filter(
                organization=self.organization,
                group=self.group,
                schedule_slot__isnull=False,
            ).exists()
        )
        self.assertTrue(self.group.teachers.filter(pk=self.teacher.pk).exists())

    def test_update_replaces_unmodified_future_lessons_without_duplicates(self):
        created = self.client.put(self.url, self.payload(), format="json")
        self.assertEqual(created.status_code, 200, created.data)
        slot_id = created.data["slots"][0]["id"]

        response = self.client.put(
            self.url,
            self.payload(id=slot_id, start_time="19:30"),
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        future = Lesson.objects.filter(
            organization=self.organization,
            group=self.group,
            starts_at__date__gt=timezone.localdate(),
        )
        self.assertTrue(future.exists())
        self.assertFalse(future.filter(starts_at__time=datetime.time(18, 0)).exists())
        self.assertEqual(future.count(), future.values("starts_at__date").distinct().count())

    def test_clear_schedule_removes_generated_future_lessons(self):
        self.client.put(self.url, self.payload(), format="json")

        response = self.client.put(
            self.url,
            {"generate_weeks_ahead": 8, "slots": []},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["slots"], [])
        self.assertFalse(
            Lesson.objects.filter(
                organization=self.organization,
                group=self.group,
                starts_at__date__gt=timezone.localdate(),
            ).exists()
        )

    def test_room_from_another_branch_is_rejected(self):
        response = self.client.put(
            self.url,
            self.payload(room=str(self.other_room.id)),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("room", response.data["slots"][0])
