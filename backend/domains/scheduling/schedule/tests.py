import datetime

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from domains.platform.tenants.models import Branch, Direction, Organization
from domains.scheduling.groups.models import Group
from domains.scheduling.schedule.models import Lesson


class LessonStatusTransitionTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.branch = Branch.objects.create(organization=self.org, name="Главный")
        self.direction = Direction.objects.create(organization=self.org, name="Балет")
        self.group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Балет — Младшая",
            capacity=12,
        )
        tz = timezone.zoneinfo.ZoneInfo("Asia/Almaty")
        self.starts_at = datetime.datetime(2026, 9, 18, 19, 0, tzinfo=tz)
        self.ends_at = datetime.datetime(2026, 9, 18, 20, 0, tzinfo=tz)
        self.lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            starts_at=self.starts_at,
            ends_at=self.ends_at,
        )

    def test_lesson_created_as_scheduled(self):
        self.assertEqual(self.lesson.status, Lesson.Status.SCHEDULED)

    def test_transition_scheduled_to_completed(self):
        self.lesson.transition_to(Lesson.Status.COMPLETED)
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, Lesson.Status.COMPLETED)

    def test_transition_scheduled_to_cancelled(self):
        self.lesson.transition_to(Lesson.Status.CANCELLED)
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, Lesson.Status.CANCELLED)

    def test_transition_completed_to_cancelled_forbidden(self):
        self.lesson.transition_to(Lesson.Status.COMPLETED)
        with self.assertRaises(ValidationError):
            self.lesson.transition_to(Lesson.Status.CANCELLED)

    def test_reschedule_links_lessons(self):
        new_lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            starts_at=self.starts_at + datetime.timedelta(days=7),
            ends_at=self.ends_at + datetime.timedelta(days=7),
        )
        self.lesson.reschedule_to(new_lesson)
        self.lesson.refresh_from_db()
        new_lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, Lesson.Status.RESCHEDULED)
        self.assertEqual(new_lesson.rescheduled_from, self.lesson)

    def test_evening_lesson_in_almaty_timezone(self):
        tz = timezone.zoneinfo.ZoneInfo("Asia/Almaty")
        starts_at = datetime.datetime(2026, 9, 18, 19, 0, tzinfo=tz)
        lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            starts_at=starts_at,
            ends_at=starts_at + datetime.timedelta(hours=1),
        )
        local_date = lesson.starts_at.astimezone(tz).date()
        self.assertEqual(local_date, datetime.date(2026, 9, 18))
        utc_date = lesson.starts_at.date()
        self.assertEqual(utc_date, datetime.date(2026, 9, 18))

    def test_tenant_isolation(self):
        org2 = Organization.objects.create(name="Other", slug="other")
        self.assertEqual(Lesson.objects.for_tenant(org2).count(), 0)
