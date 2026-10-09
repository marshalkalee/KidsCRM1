"""Бронь места на пробное из каталога (TRU-180)."""

import datetime

from django.test import TestCase
from django.utils import timezone

from domains.people.clients.models import Child
from domains.platform.leads.models import Lead
from domains.platform.public_api.catalog import offer
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group, GroupMembership

from . import holds
from .enrollment_service import EnrollOutcome, LessonService
from .models import Lesson, LessonEnrollment

TODAY = timezone.localdate()


class SeatHoldTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Центр", slug="holds")
        self.owner = User.objects.create_user(
            phone="77010000011", password="p", full_name="Владелец", organization=self.org,
            role=User.Role.OWNER,
        )  # fmt: skip
        branch = Branch.objects.create(organization=self.org, name="Алмалы")
        direction = Direction.objects.create(organization=self.org, name="Балет")
        self.group = Group.objects.create(
            organization=self.org, branch=branch, direction=direction, name="Балет 5–7",
            capacity=2, age_min=5, age_max=7, is_public=True,
        )  # fmt: skip
        self.child("Ученица")  # одно место занято, одно свободно
        start = timezone.now() + datetime.timedelta(days=1)
        self.lesson = Lesson.objects.create(
            organization=self.org, group=self.group, teacher=self.owner, starts_at=start,
            ends_at=start + datetime.timedelta(hours=1),
        )  # fmt: skip

    def child(self, name):
        child = Child.objects.create(
            organization=self.org, full_name=name, birth_date=datetime.date(2019, 1, 1)
        )
        GroupMembership.objects.create(
            organization=self.org, group=self.group, child=child, joined_at=TODAY
        )
        return child

    def hold(self, phone="77015550101"):
        return holds.hold_seat(
            organization=self.org, lesson_id=self.lesson.id, parent_name="Динара",
            phone=phone, child_name="Амина", child_age=6,
        )  # fmt: skip

    def free_seats(self):
        today = timezone.localdate()
        rows = offer(self.org, today, today + datetime.timedelta(days=7))
        return next(r["free_seats"] for r in rows if r["lesson_id"] == str(self.lesson.id))

    def test_hold_creates_marketplace_lead_and_takes_the_seat(self):
        self.assertEqual(self.free_seats(), 1)
        hold = self.hold()
        self.assertEqual(hold.lead.source.name, holds.MARKETPLACE_SOURCE)
        self.assertEqual(hold.lead.status, Lead.Status.NEW)
        self.assertEqual(hold.lead.branch_id, self.group.branch_id)
        self.assertEqual(self.free_seats(), 0)

    def test_two_parents_cannot_take_the_last_seat(self):
        self.hold()
        with self.assertRaisesMessage(holds.HoldError, "Свободных мест"):
            self.hold(phone="77015550102")
        self.assertEqual(Lead.objects.filter(organization=self.org).count(), 1)

    def test_expired_hold_frees_the_seat_by_itself(self):
        hold = self.hold()
        hold.expires_at = timezone.now() - datetime.timedelta(minutes=1)
        hold.save(update_fields=["expires_at"])
        self.assertEqual(self.free_seats(), 1)
        self.hold(phone="77015550102")  # место снова можно взять

    def test_rejected_lead_releases_the_seat(self):
        hold = self.hold()
        Lead.objects.filter(pk=hold.lead_id).update(status=Lead.Status.REJECTED)
        self.assertEqual(self.free_seats(), 1)

    def test_hold_counts_when_admin_enrolls_someone_else(self):
        self.hold()
        other = Child.objects.create(
            organization=self.org, full_name="Другая", birth_date=datetime.date(2019, 1, 1)
        )
        result = LessonService.enroll(
            self.lesson.id, other.id, LessonEnrollment.Kind.MAKEUP, actor=self.owner
        )
        self.assertEqual(result.outcome, EnrollOutcome.CAPACITY_EXCEEDED)

    def test_confirming_own_hold_is_allowed_and_not_counted_twice(self):
        hold = self.hold()
        child = Child.objects.create(
            organization=self.org, full_name="Амина", birth_date=datetime.date(2019, 1, 1)
        )
        result = LessonService.enroll(
            self.lesson.id, child.id, LessonEnrollment.Kind.TRIAL, actor=self.owner,
            source_lead_id=hold.lead_id,
        )  # fmt: skip
        self.assertEqual(result.outcome, EnrollOutcome.ENROLLED)
        self.assertEqual(self.free_seats(), 0)  # запись есть, бронь больше не считается
        self.assertFalse(holds.active().filter(pk=hold.pk).exists())

    def test_no_hold_without_trial_or_on_private_or_past_lessons(self):
        Group.objects.filter(pk=self.group.pk).update(trial_available=False)
        with self.assertRaisesMessage(holds.HoldError, "нет пробных"):
            self.hold()
        Group.objects.filter(pk=self.group.pk).update(trial_available=True, is_public=False)
        with self.assertRaisesMessage(holds.HoldError, "не найдено"):
            self.hold()

    def test_catalog_shows_trial_terms(self):
        Group.objects.filter(pk=self.group.pk).update(trial_price=2000)
        today = timezone.localdate()
        row = offer(self.org, today, today + datetime.timedelta(days=7))[0]
        self.assertEqual(row["group"]["trial"], {"available": True, "price": 2000})
