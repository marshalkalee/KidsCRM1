from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from domains.people.clients.models import Child
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User
from domains.scheduling.attendance.models import Attendance
from domains.scheduling.schedule.models import Lesson

from .no_subscription import children_without_subscription, sell_and_cover, total_unpaid_lessons
from .subscription_types import create_type


class NoSubscriptionTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.branch = Branch.objects.create(organization=self.org, name="Филиал на Абая")
        self.ballet = Direction.objects.create(organization=self.org, name="Балет")
        self.child = Child.objects.create(
            organization=self.org,
            full_name="Иванов Алихан",
            birth_date=date(2018, 1, 1),
            gender=Child.Gender.MALE,
        )
        self.child.directions.add(self.ballet)
        self.admin = User.objects.create_user(
            phone="77001112233",
            password="pass",
            full_name="Админ",
            organization=self.org,
            role=User.Role.ADMIN,
        )
        past = timezone.now() - timedelta(days=3)
        self.lesson = Lesson.objects.create(
            organization=self.org, starts_at=past, ends_at=past + timedelta(hours=1)
        )
        self.attendance = Attendance(
            organization=self.org, lesson=self.lesson, child=self.child, status=""
        )

    def test_mark_present_without_subscription_sets_flag(self):
        self.attendance.mark(Attendance.Status.PRESENT, actor=self.admin)
        self.assertTrue(self.attendance.no_subscription_flag)

    def test_children_without_subscription_lists_correctly(self):
        self.attendance.mark(Attendance.Status.PRESENT, actor=self.admin)
        rows = list(children_without_subscription(self.org))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["lessons_count"], 1)
        self.assertEqual(total_unpaid_lessons(self.org), 1)

    def test_sell_and_cover_backdated_resolves_attendance(self):
        self.attendance.mark(Attendance.Status.PRESENT, actor=self.admin)
        self.assertTrue(self.attendance.no_subscription_flag)

        st = create_type(
            self.org,
            name="8 занятий",
            price=30000,
            quota_sessions=8,
            duration_days=30,
            directions=[self.ballet],
        )
        subscription, _payment, covered = sell_and_cover(
            self.child,
            actor=self.admin,
            subscription_type_version=st.versions.latest(),
            direction=self.ballet,
            branch=self.branch,
            starts_on=date.today() - timedelta(days=5),
            ends_on=date.today() + timedelta(days=25),
            paid_amount=30000,
            payment_method="cash",
        )
        self.assertEqual(covered, 1)
        self.assertEqual(subscription.sessions_remaining_cache, 7)

        self.attendance.refresh_from_db()
        self.assertFalse(self.attendance.no_subscription_flag)
        self.assertTrue(self.attendance.consumed_from_subscription)
        self.assertEqual(total_unpaid_lessons(self.org), 0)
