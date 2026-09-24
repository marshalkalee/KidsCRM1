import datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from domains.people.clients.models import Child
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.schedule.models import Lesson

User = get_user_model()


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


class LessonCalendarApiTest(APITestCase):
    """
    Календарь (TRU-44): один запрос на весь диапазон дат, без запроса на
    занятие (ТЗ п. 10.2 — ≤ 1с при 500 занятиях в неделю).
    """

    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.branch = Branch.objects.create(organization=self.org, name="Главный")
        self.direction = Direction.objects.create(
            organization=self.org, name="Балет", color="#AA00FF"
        )
        self.group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Балет — Младшая",
            capacity=12,
        )
        self.teacher = User.objects.create_user(
            phone="+77010000010",
            full_name="Преподаватель",
            password="pass12345",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        self.owner = User.objects.create_user(
            phone="+77010000011",
            full_name="Владелец",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )
        for i in range(3):
            child = Child.objects.create(
                organization=self.org,
                full_name=f"Ребёнок {i}",
                birth_date=datetime.date.today() - datetime.timedelta(days=365 * 7),
                gender=Child.Gender.FEMALE,
            )
            GroupMembership.objects.create(
                organization=self.org,
                group=self.group,
                child=child,
                joined_at=datetime.date.today(),
            )

        tz = timezone.zoneinfo.ZoneInfo("Asia/Almaty")
        self.week_start = datetime.datetime(2026, 9, 21, 9, 0, tzinfo=tz)
        for i in range(20):
            Lesson.objects.create(
                organization=self.org,
                group=self.group,
                teacher=self.teacher,
                starts_at=self.week_start + datetime.timedelta(days=i % 7, hours=i),
                ends_at=self.week_start + datetime.timedelta(days=i % 7, hours=i + 1),
            )

    def test_week_range_returns_calendar_fields_without_pagination(self):
        self.client.force_authenticate(self.owner)

        response = self.client.get(
            "/api/v1/schedule/",
            {"date_from": "2026-09-21", "date_to": "2026-09-27"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertEqual(len(response.data), 20)
        lesson = response.data[0]
        self.assertEqual(lesson["direction_color"], "#AA00FF")
        self.assertEqual(lesson["group_name"], "Балет — Младшая")
        self.assertEqual(lesson["capacity"], 12)
        self.assertEqual(lesson["enrolled_count"], 3)
        self.assertEqual(lesson["teacher_name"], "Преподаватель")

    def test_query_count_does_not_grow_with_lesson_count(self):
        self.client.force_authenticate(self.owner)
        params = {"date_from": "2026-09-21", "date_to": "2026-09-27"}

        with CaptureQueriesContext(connection) as small:
            self.client.get("/api/v1/schedule/", params)

        # Ещё занятия в том же диапазоне — число запросов не должно расти.
        for i in range(20, 60):
            Lesson.objects.create(
                organization=self.org,
                group=self.group,
                teacher=self.teacher,
                starts_at=self.week_start + datetime.timedelta(days=i % 7, hours=i),
                ends_at=self.week_start + datetime.timedelta(days=i % 7, hours=i + 1),
            )

        with CaptureQueriesContext(connection) as large:
            response = self.client.get("/api/v1/schedule/", params)

        self.assertEqual(len(response.data), 60)
        self.assertEqual(len(small.captured_queries), len(large.captured_queries))
