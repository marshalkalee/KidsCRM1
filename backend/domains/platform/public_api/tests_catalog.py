"""Публичный срез предложения центра — задел под маркетплейс (TRU-177)."""

import datetime
import json

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from domains.money.subscriptions.subscription_types import create_type
from domains.people.clients.models import Child
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.schedule.models import Lesson, LessonEnrollment

from .catalog import LESSON_FIELDS, offer

TODAY = timezone.localdate()


class CatalogTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Центр", slug="catalog")
        self.owner = User.objects.create_user(
            phone="77010000001", password="p", full_name="Владелец", organization=self.org,
            role=User.Role.OWNER,
        )  # fmt: skip
        self.branch = Branch.objects.create(
            organization=self.org, name="Алмалы", address="Алматы, Абая 10"
        )
        self.ballet = Direction.objects.create(organization=self.org, name="Балет")
        self.public = self.group("Балет 5–7", capacity=5, public=True)
        self.private = self.group("Закрытая", capacity=8, public=False)
        self.members = [self.child(f"Ученица {i}", self.public) for i in range(3)]
        self.lesson = self.make_lesson(self.public)
        outsider = self.child("Отработка", self.private)
        self.enroll(outsider)  # поверх группы — занимает место
        self.enroll(self.members[0])  # уже в группе — второй раз не считается
        cancelled = self.child("Отменила", self.private)
        self.enroll(cancelled, cancelled_at=timezone.now())  # отменена — не считается
        self.make_lesson(self.private)
        create_type(
            self.org, name="8 занятий", price=25000, quota_sessions=8, duration_days=30,
            directions=[self.ballet],
        ).__class__.objects.filter(name="8 занятий").update(is_public=True)  # fmt: skip
        create_type(self.org, name="Внутренний", price=1000, quota_sessions=1, duration_days=7)

    def group(self, name, *, capacity, public):
        return Group.objects.create(
            organization=self.org, branch=self.branch, direction=self.ballet, name=name,
            capacity=capacity, age_min=5, age_max=7, is_public=public,
        )  # fmt: skip

    def child(self, name, group):
        child = Child.objects.create(
            organization=self.org, full_name=name, birth_date=datetime.date(2019, 1, 1)
        )
        GroupMembership.objects.create(
            organization=self.org, group=group, child=child, joined_at=TODAY
        )
        return child

    def make_lesson(self, group, days=0):
        start = timezone.now() + datetime.timedelta(days=days)
        return Lesson.objects.create(
            organization=self.org, group=group, teacher=self.owner, starts_at=start,
            ends_at=start + datetime.timedelta(hours=1),
        )  # fmt: skip

    def enroll(self, child, cancelled_at=None):
        return LessonEnrollment.objects.create(
            organization=self.org, lesson=self.lesson, child=child, kind="makeup",
            cancelled_at=cancelled_at,
        )  # fmt: skip

    def week(self, **kwargs):
        return offer(
            self.org,
            TODAY - datetime.timedelta(days=1),
            TODAY + datetime.timedelta(days=7),
            **kwargs,
        )

    def test_only_groups_the_center_published(self):
        rows = self.week()
        self.assertEqual({r["group"]["name"] for r in rows}, {"Балет 5–7"})
        self.assertEqual(len(self.week(include_private=True)), 2)

    def test_free_seats_match_participants(self):
        row = self.week()[0]
        taken = self.lesson.participants().count()
        self.assertEqual(taken, 4)  # трое из группы + одна отработка
        self.assertEqual(row["free_seats"], 5 - taken)
        self.assertEqual((row["group"]["age_min"], row["group"]["age_max"]), (5, 7))
        self.assertEqual(row["branch"]["address"], "Алматы, Абая 10")

    def test_only_public_prices(self):
        self.assertEqual(
            self.week()[0]["prices"],
            [{"name": "8 занятий", "price": 25000, "sessions": 8, "days": 30}],
        )

    def test_no_personal_data(self):
        rows = self.week(include_private=True)
        self.assertTrue(all(set(r) == set(LESSON_FIELDS) for r in rows))
        dump = json.dumps(rows, ensure_ascii=False)
        for name in ["Ученица", "Отработка", "Отменила", "Владелец", "77010000001"]:
            self.assertNotIn(name, dump)

    def test_query_count_does_not_grow_with_lessons(self):
        with CaptureQueriesContext(connection) as few:
            self.week(include_private=True)
        for day in range(1, 7):
            self.make_lesson(self.public, days=day)
            self.make_lesson(self.private, days=day)
        with CaptureQueriesContext(connection) as many:
            rows = self.week(include_private=True)
        self.assertEqual(len(rows), 14)
        self.assertEqual(len(few.captured_queries), len(many.captured_queries))
