"""
TRU-132: проверки заморозки, найденные на ревью TRU-63.
1. Даты: конец раньше начала не принимается — срок не уезжает назад.
2. Пересечения: два раза за одни и те же дни срок не продлевается.
3. Будущий старт: до начала заморозки абонемент действует и списывает занятия,
   «заморожен» он с даты начала (ночная задача), после конца снова действует.
4. Неактивный абонемент: понятная ошибка, а не «Недопустимый переход …».
"""

import uuid
from datetime import date, timedelta

from django.test import TestCase, tag
from rest_framework.test import APITestCase

from domains.people.clients.models import Child
from domains.platform.core.audit import AuditLog
from domains.platform.core.utils import today_for_org
from domains.platform.tenants.models import Direction, Organization
from domains.platform.users.models import User

from .freezes import freeze_subscription, unfreeze_subscription
from .models import Subscription, SubscriptionFreeze
from .statuses import _update_organization
from .subscription_service import ConsumeOutcome, SubscriptionService
from .subscription_types import create_type


def make_subscription(slug, phone):
    org = Organization.objects.create(name=slug, slug=slug)
    ballet = Direction.objects.create(organization=org, name="Балет")
    child = Child.objects.create(
        organization=org,
        full_name="Иванов Алихан",
        birth_date=date(2018, 1, 1),
        gender=Child.Gender.MALE,
    )
    admin = User.objects.create_user(
        phone=phone,
        password="pass",
        full_name="Админ",
        organization=org,
        role=User.Role.ADMIN,
    )
    st = create_type(
        org, name="8 занятий", price=25000, quota_sessions=8, duration_days=30, directions=[ballet]
    )
    today = today_for_org(org)
    sub = Subscription.objects.create(
        organization=org,
        child=child,
        subscription_type_version=st.versions.latest(),
        direction=ballet,
        starts_on=today - timedelta(days=5),
        ends_on=today + timedelta(days=25),
        list_price=25000,
        price=25000,
        sessions_remaining_cache=8,
    )
    return org, admin, sub


class FreezeChecksBase(TestCase):
    def setUp(self):
        self.org, self.admin, self.sub = make_subscription("true-ballet", "77001112233")
        self.today = today_for_org(self.org)
        self.original_end = self.sub.ends_on

    def freeze(self, start_offset, end_offset, sub=None):
        return freeze_subscription(
            sub or self.sub,
            actor=self.admin,
            starts_on=self.today + timedelta(days=start_offset),
            ends_on=self.today + timedelta(days=end_offset),
        )

    def nightly(self, day_offset):
        _update_organization(self.org, self.today + timedelta(days=day_offset))
        self.sub.refresh_from_db()

    def consume(self):
        return SubscriptionService.consume(self.sub.child_id, uuid.uuid4(), self.sub.direction_id)


class FreezeDatesTests(FreezeChecksBase):
    """Пункт 1: конец заморозки раньше начала."""

    def test_end_before_start_is_rejected(self):
        with self.assertRaisesMessage(ValueError, "позже даты начала"):
            self.freeze(10, 3)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.ends_on, self.original_end)
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)
        self.assertFalse(SubscriptionFreeze.objects.exists())
        self.assertFalse(AuditLog.objects.filter(action=AuditLog.Action.FREEZE).exists())

    def test_zero_length_is_rejected(self):
        with self.assertRaisesMessage(ValueError, "позже даты начала"):
            self.freeze(0, 0)
        self.assertFalse(SubscriptionFreeze.objects.exists())


class FreezeOverlapTests(FreezeChecksBase):
    """Пункт 2: пересечения с другими заморозками того же абонемента."""

    def test_overlapping_freeze_is_rejected_and_end_moves_once(self):
        self.freeze(1, 11)
        with self.assertRaisesMessage(ValueError, "пересекаются с другой заморозкой"):
            self.freeze(5, 15)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.ends_on, self.original_end + timedelta(days=10))
        self.assertEqual(self.sub.freezes.count(), 1)

    def test_same_period_twice_is_rejected(self):
        self.freeze(3, 10)
        with self.assertRaises(ValueError):
            self.freeze(3, 10)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.ends_on, self.original_end + timedelta(days=7))

    def test_shared_boundary_day_is_overlap(self):
        # Последний день заморозки тоже заморожен: следующая с него начаться не может.
        self.freeze(3, 10)
        with self.assertRaises(ValueError):
            self.freeze(10, 15)

    def test_inner_period_is_rejected(self):
        self.freeze(2, 20)
        with self.assertRaises(ValueError):
            self.freeze(5, 6)

    def test_back_to_back_freezes_are_allowed(self):
        self.freeze(3, 10)
        self.freeze(11, 15)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.ends_on, self.original_end + timedelta(days=11))
        self.assertEqual(self.sub.freezes.count(), 2)

    def test_freeze_cancelled_on_its_first_day_does_not_block(self):
        self.freeze(0, 10)
        unfreeze_subscription(self.sub, actor=self.admin)  # в тот же день: 0 дней
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.ends_on, self.original_end)
        self.freeze(0, 7)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.ends_on, self.original_end + timedelta(days=7))

    def test_unfreeze_cannot_stretch_into_next_freeze(self):
        self.freeze(8, 12)
        self.freeze(0, 5)
        self.sub.refresh_from_db()
        end = self.sub.ends_on
        with self.assertRaisesMessage(ValueError, "пересекаются с другой заморозкой"):
            unfreeze_subscription(
                self.sub, actor=self.admin, actual_end_date=self.today + timedelta(days=9)
            )
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.ends_on, end)
        self.assertEqual(self.sub.status, Subscription.Status.FROZEN)


class FutureFreezeTests(FreezeChecksBase):
    """Пункт 3: заморозка с будущей датой старта."""

    def test_future_freeze_keeps_subscription_active_and_consuming(self):
        self.freeze(3, 10)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)
        self.assertEqual(self.sub.ends_on, self.original_end + timedelta(days=7))

        result = self.consume()
        self.assertEqual(result.outcome, ConsumeOutcome.CONSUMED)
        self.assertEqual(result.subscription_id, self.sub.id)

    def test_nightly_freezes_on_start_day_and_unfreezes_after_end(self):
        self.freeze(3, 10)
        self.sub.refresh_from_db()
        end = self.sub.ends_on

        self.nightly(2)
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)

        self.nightly(3)
        self.assertEqual(self.sub.status, Subscription.Status.FROZEN)
        self.assertEqual(self.consume().outcome, ConsumeOutcome.SUBSCRIPTION_FROZEN)
        self.assertTrue(
            AuditLog.objects.filter(
                object_id=self.sub.id, action=AuditLog.Action.FREEZE, actor=None
            ).exists()
        )

        self.nightly(10)  # последний день заморозки — ещё заморожен
        self.assertEqual(self.sub.status, Subscription.Status.FROZEN)

        self.nightly(11)
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)
        # Срок сдвинут один раз — при оформлении, ночная задача его не трогает.
        self.assertEqual(self.sub.ends_on, end)

    def test_nightly_is_idempotent(self):
        self.freeze(3, 10)
        self.nightly(4)
        self.nightly(4)
        self.assertEqual(self.sub.status, Subscription.Status.FROZEN)
        self.assertEqual(
            AuditLog.objects.filter(
                object_id=self.sub.id, action=AuditLog.Action.FREEZE, actor=None
            ).count(),
            1,
        )

    def test_back_to_back_freezes_stay_frozen_between_them(self):
        # Заморозить можно только действующий: следующую оформляют заранее.
        self.freeze(6, 9)
        self.freeze(0, 5)
        self.nightly(6)
        self.assertEqual(self.sub.status, Subscription.Status.FROZEN)
        self.nightly(10)
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)

    def test_freeze_starting_today_freezes_at_once(self):
        self.freeze(0, 7)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.FROZEN)
        self.assertEqual(self.consume().outcome, ConsumeOutcome.SUBSCRIPTION_FROZEN)

    def test_freeze_started_earlier_freezes_at_once(self):
        self.freeze(-3, 4)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.FROZEN)

    def test_freeze_fully_in_past_only_moves_end(self):
        self.freeze(-5, -2)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)
        self.assertEqual(self.sub.ends_on, self.original_end + timedelta(days=3))

    def test_frozen_too_early_before_fix_is_released_by_nightly(self):
        # Так абонемент мог замёрзнуть до TRU-132: заморозка ещё не началась.
        SubscriptionFreeze.objects.create(
            organization=self.org,
            subscription=self.sub,
            starts_on=self.today + timedelta(days=4),
            ends_on=self.today + timedelta(days=9),
        )
        Subscription.objects.filter(pk=self.sub.pk).update(status=Subscription.Status.FROZEN)
        self.nightly(0)
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)
        self.nightly(4)
        self.assertEqual(self.sub.status, Subscription.Status.FROZEN)

    def test_unfreeze_ends_running_freeze_not_planned_one(self):
        self.freeze(10, 15)
        self.freeze(-2, 3)
        self.sub.refresh_from_db()
        unfreeze_subscription(self.sub, actor=self.admin)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)
        running = self.sub.freezes.get(starts_on=self.today - timedelta(days=2))
        planned = self.sub.freezes.get(starts_on=self.today + timedelta(days=10))
        self.assertEqual(running.ends_on, self.today)
        self.assertEqual(planned.ends_on, self.today + timedelta(days=15))
        # 5 дней запланированных − 3 неиспользованных + 5 дней будущей заморозки.
        self.assertEqual(self.sub.ends_on, self.original_end + timedelta(days=7))

    def test_parent_portal_shows_running_freeze_not_planned_one(self):
        from domains.people.portal.summary import subscription_row

        self.freeze(10, 15)
        self.freeze(-2, 3)
        self.sub.refresh_from_db()
        row = subscription_row(self.sub)
        self.assertEqual(row["freeze"]["starts_on"], self.today - timedelta(days=2))

    def test_unfreeze_with_future_date_stays_frozen_until_then(self):
        self.freeze(0, 14)
        unfreeze_subscription(
            self.sub, actor=self.admin, actual_end_date=self.today + timedelta(days=5)
        )
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.ends_on, self.original_end + timedelta(days=5))
        self.assertEqual(self.sub.status, Subscription.Status.FROZEN)
        self.nightly(6)
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)


class FreezeInactiveTests(FreezeChecksBase):
    """Пункт 4: заморозить можно только действующий абонемент."""

    def assert_rejected(self, status, label):
        Subscription.objects.filter(pk=self.sub.pk).update(status=status)
        with self.assertRaises(ValueError) as caught:
            self.freeze(1, 5)
        message = str(caught.exception)
        self.assertIn("только действующий абонемент", message)
        self.assertIn(label, message)
        self.assertNotIn("Недопустимый переход", message)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.ends_on, self.original_end)
        self.assertFalse(SubscriptionFreeze.objects.exists())

    def test_expired(self):
        self.assert_rejected(Subscription.Status.EXPIRED, "Истёк")

    def test_exhausted(self):
        self.assert_rejected(Subscription.Status.EXHAUSTED, "Исчерпан")

    def test_already_frozen(self):
        self.assert_rejected(Subscription.Status.FROZEN, "Заморожен")

    def test_stale_object_is_checked_against_database(self):
        # Объект прочитан до того, как абонемент истёк: проверка — по базе.
        stale = Subscription.objects.get(pk=self.sub.pk)
        Subscription.objects.filter(pk=self.sub.pk).update(status=Subscription.Status.EXPIRED)
        with self.assertRaisesMessage(ValueError, "только действующий абонемент"):
            self.freeze(1, 5, sub=stale)


class FreezeChecksApiTests(APITestCase):
    def setUp(self):
        self.org, admin, self.sub = make_subscription("true-ballet", "77001112233")
        self.today = today_for_org(self.org)
        self.client.force_authenticate(admin)

    def freeze(self, start_offset, end_offset):
        return self.client.post(
            f"/api/v1/subscriptions/{self.sub.pk}/freeze/",
            {
                "starts_on": (self.today + timedelta(days=start_offset)).isoformat(),
                "ends_on": (self.today + timedelta(days=end_offset)).isoformat(),
            },
        )

    def test_end_before_start_is_field_error(self):
        response = self.freeze(5, 2)
        self.assertEqual(response.status_code, 400)
        self.assertIn("ends_on", response.data)

    def test_overlap_is_readable(self):
        self.assertEqual(self.freeze(3, 10).status_code, 200)
        response = self.freeze(8, 12)
        self.assertEqual(response.status_code, 400)
        self.assertIn("пересекаются", response.data["detail"])

    def test_future_freeze_is_planned_not_frozen(self):
        response = self.freeze(3, 10)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "active")
        self.assertEqual(len(response.data["freezes"]), 1)

    def test_inactive_is_readable(self):
        Subscription.objects.filter(pk=self.sub.pk).update(status=Subscription.Status.EXHAUSTED)
        response = self.freeze(1, 5)
        self.assertEqual(response.status_code, 400)
        self.assertIn("только действующий абонемент", response.data["detail"])


@tag("tenant_isolation")
class FreezeOverlapIsolationTests(TestCase):
    def test_other_center_freezes_do_not_count(self):
        org_a, admin_a, sub_a = make_subscription("a", "77010000000")
        org_b, admin_b, sub_b = make_subscription("b", "77020000000")
        today = today_for_org(org_a)
        freeze_subscription(
            sub_b,
            actor=admin_b,
            starts_on=today + timedelta(days=1),
            ends_on=today + timedelta(days=9),
        )
        freeze_subscription(
            sub_a,
            actor=admin_a,
            starts_on=today + timedelta(days=1),
            ends_on=today + timedelta(days=9),
        )
        self.assertEqual(sub_a.freezes.count(), 1)
        _update_organization(org_a, today + timedelta(days=2))
        sub_a.refresh_from_db()
        sub_b.refresh_from_db()
        self.assertEqual(sub_a.status, Subscription.Status.FROZEN)
        # Ночная задача центра A не трогает абонементы центра B.
        self.assertEqual(sub_b.status, Subscription.Status.ACTIVE)
