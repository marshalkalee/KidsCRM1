"""Parent portal schedule API."""

import datetime

from django.utils import timezone

from domains.people.clients.models import Child
from domains.platform.tenants.models import Direction
from domains.scheduling.attendance.models import Attendance
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.schedule.models import Lesson, LessonEnrollment

from .tests_auth import PortalAuthBase


class ParentScheduleTests(PortalAuthBase):
    def setUp(self):
        super().setUp()
        self.branch = self.org.branch_set.first()
        self.direction = Direction.objects.create(organization=self.org, name="Балет")
        self.group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Балет 8–11",
            capacity=12,
        )
        self.tz = timezone.zoneinfo.ZoneInfo(self.org.timezone or "Asia/Almaty")
        self.today = timezone.now().astimezone(self.tz).date()
        GroupMembership.objects.create(
            organization=self.org,
            group=self.group,
            child=self.child,
            joined_at=self.today,
        )

    def lesson(self, day, hour=18, *, group=True):
        starts_at = datetime.datetime.combine(day, datetime.time(hour), tzinfo=self.tz)
        lesson_group = self.group if group is True else group or None
        return Lesson.objects.create(
            organization=self.org,
            group=lesson_group,
            starts_at=starts_at,
            ends_at=starts_at + datetime.timedelta(hours=1),
        )

    def get(self, suffix=""):
        token = self.login()
        return self.as_parent(token).get(
            f"/api/v1/portal/children/{self.child.id}/schedule/{suffix}"
        )

    def test_shows_group_individual_and_extra_lessons(self):
        group_lesson = self.lesson(self.today + datetime.timedelta(days=1))
        individual = self.lesson(self.today + datetime.timedelta(days=2), group=False)
        individual.individual_children.add(self.child)
        extra = self.lesson(self.today + datetime.timedelta(days=3), group=False)
        LessonEnrollment.objects.create(
            organization=self.org,
            lesson=extra,
            child=self.child,
            kind=LessonEnrollment.Kind.MAKEUP,
        )

        response = self.get()

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["results"]), 3)
        by_id = {str(row["id"]): row for row in response.data["results"]}
        self.assertEqual(by_id[str(group_lesson.id)]["group_name"], self.group.name)
        self.assertIsNone(by_id[str(individual.id)]["enrollment_kind"])
        self.assertEqual(by_id[str(extra.id)]["enrollment_kind"], "makeup")
        self.assertNotIn("note", by_id[str(group_lesson.id)])

    def test_foreign_child_is_not_disclosed(self):
        stranger = Child.objects.create(
            organization=self.org,
            full_name="Чужой ребёнок",
            birth_date=datetime.date(2018, 1, 1),
        )
        token = self.login()
        response = self.as_parent(token).get(f"/api/v1/portal/children/{stranger.id}/schedule/")
        self.assertEqual(response.status_code, 404)

    def test_parent_authentication_is_required(self):
        response = self.api.get(f"/api/v1/portal/children/{self.child.id}/schedule/")
        self.assertEqual(response.status_code, 401)

    def test_parent_can_choose_and_book_valid_makeup(self):
        source_lesson = self.lesson(self.today - datetime.timedelta(days=1))
        source = Attendance.objects.create(
            organization=self.org,
            lesson=source_lesson,
            child=self.child,
            status=Attendance.Status.ABSENT,
        )
        other_group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Балет 12–15",
            capacity=10,
        )
        candidate = self.lesson(self.today + datetime.timedelta(days=2), group=other_group)
        token = self.login()
        client = self.as_parent(token)
        url = f"/api/v1/portal/children/{self.child.id}/makeups/{source.id}/"

        options = client.get(url)
        self.assertEqual(options.status_code, 200, options.data)
        self.assertEqual([str(row["id"]) for row in options.data["results"]], [str(candidate.id)])

        booked = client.post(url, {"lesson_id": str(candidate.id)}, format="json")
        self.assertEqual(booked.status_code, 201, booked.data)
        enrollment = LessonEnrollment.objects.get(id=booked.data["enrollment_id"])
        self.assertEqual(enrollment.kind, LessonEnrollment.Kind.MAKEUP)
        self.assertEqual(enrollment.source_attendance, source)

        repeated = client.post(url, {"lesson_id": str(candidate.id)}, format="json")
        self.assertEqual(repeated.status_code, 409)

    def test_makeup_rejects_foreign_child(self):
        source_lesson = self.lesson(self.today - datetime.timedelta(days=1))
        source = Attendance.objects.create(
            organization=self.org,
            lesson=source_lesson,
            child=self.child,
            status=Attendance.Status.ABSENT,
        )
        stranger = Child.objects.create(
            organization=self.org,
            full_name="Чужой ребёнок",
            birth_date=datetime.date(2018, 1, 1),
        )
        token = self.login()
        response = self.as_parent(token).get(
            f"/api/v1/portal/children/{stranger.id}/makeups/{source.id}/"
        )
        self.assertEqual(response.status_code, 404)
