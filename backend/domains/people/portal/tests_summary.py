"""
Главный экран кабинета (TRU-138): ближайшие занятия по тому же правилу,
что Lesson.participants; абонемент и «к оплате» — те же цифры, что у
администратора; чужой ребёнок — 404.
"""

from datetime import date, timedelta

from django.utils import timezone

from domains.money.payments.services import record_payment
from domains.money.subscriptions.debt import debt_by_child
from domains.money.subscriptions.models import Subscription
from domains.money.subscriptions.subscription_types import create_type
from domains.platform.tenants.models import Branch, Direction, Room
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.schedule.models import Lesson, LessonEnrollment

from .tests_auth import PortalAuthBase, family


class ParentHomeTests(PortalAuthBase):
    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.create(
            organization=self.org, name="Абая", address="пр. Абая, 150"
        )
        self.room = Room.objects.create(
            organization=self.org, branch=self.branch, name="Большой зал"
        )
        self.ballet = Direction.objects.create(organization=self.org, name="Балет")
        self.teacher = User.objects.create_user(
            phone="+77010000055",
            password="x",
            full_name="Динара Сейтказы",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        self.group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.ballet,
            name="Балет 4–9",
            capacity=12,
        )
        GroupMembership.objects.create(
            organization=self.org, child=self.child, group=self.group, joined_at=date(2026, 9, 1)
        )
        self.client = self.as_parent(self.login())

    def lesson(self, hours, group=None, status=Lesson.Status.SCHEDULED):
        starts = timezone.now() + timedelta(hours=hours)
        return Lesson.objects.create(
            organization=self.org,
            group=group,
            room=self.room,
            teacher=self.teacher,
            starts_at=starts,
            ends_at=starts + timedelta(hours=1),
            status=status,
        )

    def summary(self, child=None):
        return self.client.get(f"/api/v1/portal/children/{(child or self.child).id}/summary/")

    def test_next_lessons_follow_participants_rule(self):
        self.lesson(-2, self.group)  # прошло
        self.lesson(5, self.group, status=Lesson.Status.CANCELLED)  # отменено
        group_lesson = self.lesson(24, self.group)
        individual = self.lesson(48)
        individual.individual_children.add(self.child)
        other_group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.ballet,
            name="Балет 10–14",
            capacity=12,
        )
        makeup = self.lesson(72, other_group)
        LessonEnrollment.objects.create(
            organization=self.org,
            lesson=makeup,
            child=self.child,
            kind=LessonEnrollment.Kind.MAKEUP,
        )
        self.lesson(30, other_group)  # чужая группа без записи — не его

        rows = self.summary().data["next_lessons"]
        self.assertEqual(
            [r["id"] for r in rows], [str(group_lesson.id), str(individual.id), str(makeup.id)]
        )
        self.assertEqual([r["kind"] for r in rows], ["group", "individual", "makeup"])
        first = rows[0]
        self.assertEqual(
            (first["group"], first["branch"], first["room"], first["teacher"]),
            ("Балет 4–9", "Абая", "Большой зал", "Динара Сейтказы"),
        )
        self.assertTrue(first["starts_at"].endswith("+05:00"))  # время центра (Asia/Almaty)

    def test_left_group_lessons_are_not_shown(self):
        self.lesson(24, self.group)
        GroupMembership.objects.filter(child=self.child).update(left_at=date(2026, 9, 20))
        self.assertEqual(self.summary().data["next_lessons"], [])

    def test_subscription_and_to_pay_match_admin(self):
        version = create_type(
            self.org,
            name="8 занятий",
            price=30000,
            quota_sessions=8,
            duration_days=30,
            directions=[self.ballet],
        ).versions.latest()
        subscription = Subscription.objects.create(
            organization=self.org,
            child=self.child,
            subscription_type_version=version,
            direction=self.ballet,
            starts_on=date.today(),
            ends_on=date.today() + timedelta(days=30),
            list_price=30000,
            price=30000,
        )
        owner = User.objects.create_user(
            phone="+77010000056",
            password="x",
            full_name="Админ",
            organization=self.org,
            role=User.Role.ADMIN,
        )
        record_payment(actor=owner, subscription=subscription, amount=12000, method="cash")
        data = self.summary().data
        self.assertEqual(
            data["to_pay"], str(debt_by_child(self.org, [self.child.id])[self.child.id])
        )
        self.assertEqual(data["to_pay"], "18000")
        sub = data["subscription"]
        self.assertEqual(
            (sub["name"], sub["sessions_total"], sub["status"]), ("8 занятий", 8, "active")
        )
        self.assertEqual(
            sub["sessions_remaining"], Subscription.objects.get().sessions_remaining_cache
        )

    def test_no_subscription_and_nothing_to_pay(self):
        data = self.summary().data
        self.assertIsNone(data["subscription"])
        self.assertEqual(data["to_pay"], "0")

    def test_foreign_child_is_404(self):
        _, (stranger,) = family(self.org, "Чужая мама", "+77019990000", "Чужой Ребёнок")
        self.assertEqual(self.summary(stranger).status_code, 404)
