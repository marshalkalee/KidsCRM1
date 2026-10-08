import threading
import uuid
from datetime import date, timedelta
from unittest.mock import patch

from django.db import connection
from django.test import TestCase, TransactionTestCase

from domains.people.clients.models import Child
from domains.platform.core.utils import today_for_org
from domains.platform.tenants.models import Direction, Organization

from . import subscription_service
from .models import LessonConsumption, Subscription, SubscriptionLedgerEntry
from .subscription_service import ConsumeOutcome, SubscriptionService
from .subscription_types import create_type
from .subscriptions import add_ledger_entry


class SubscriptionFixtureMixin:
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.ballet = Direction.objects.create(organization=self.org, name="Балет")
        self.child = Child.objects.create(
            organization=self.org,
            full_name="Иванов Алихан",
            birth_date=date(2018, 1, 1),
            gender=Child.Gender.MALE,
        )
        self.today = today_for_org(self.org)
        self.sub = self.make_subscription()
        self.lesson_id = uuid.uuid4()

    def make_subscription(self, sessions=8, starts_on=None, ends_on=None, status=None):
        st = create_type(
            self.org,
            name=f"{sessions} занятий",
            price=25000,
            quota_sessions=sessions,
            duration_days=30,
            directions=[self.ballet],
        )
        sub = Subscription.objects.create(
            organization=self.org,
            child=self.child,
            subscription_type_version=st.versions.latest(),
            direction=self.ballet,
            starts_on=starts_on or self.today,
            ends_on=ends_on or self.today + timedelta(days=30),
            status=status or Subscription.Status.ACTIVE,
            list_price=25000,
            price=25000,
        )
        add_ledger_entry(sub, kind=SubscriptionLedgerEntry.Kind.INITIAL_GRANT, delta=sessions)
        return sub

    def consume(self, lesson_id=None, **kwargs):
        return SubscriptionService.consume(
            self.child.id, lesson_id or uuid.uuid4(), self.ballet.id, **kwargs
        )


class ConsumeTests(SubscriptionFixtureMixin, TestCase):
    def test_consume_success(self):
        result = SubscriptionService.consume(self.child.id, self.lesson_id, self.ballet.id)
        self.assertEqual(result.outcome, ConsumeOutcome.CONSUMED)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.sessions_remaining_cache, 7)

    def test_consume_idempotent(self):
        SubscriptionService.consume(self.child.id, self.lesson_id, self.ballet.id)
        SubscriptionService.consume(self.child.id, self.lesson_id, self.ballet.id)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.sessions_remaining_cache, 7)

    def test_no_active_subscription(self):
        self.sub.status = Subscription.Status.EXPIRED
        self.sub.save()
        result = SubscriptionService.consume(self.child.id, uuid.uuid4(), self.ballet.id)
        self.assertEqual(result.outcome, ConsumeOutcome.NO_ACTIVE_SUBSCRIPTION)

    def test_frozen_subscription(self):
        self.sub.status = Subscription.Status.FROZEN
        self.sub.save()
        result = SubscriptionService.consume(self.child.id, self.lesson_id, self.ballet.id)
        self.assertEqual(result.outcome, ConsumeOutcome.SUBSCRIPTION_FROZEN)

    def test_exhausted_subscription(self):
        self.sub.sessions_remaining_cache = 0
        self.sub.save()
        result = SubscriptionService.consume(self.child.id, self.lesson_id, self.ballet.id)
        self.assertEqual(result.outcome, ConsumeOutcome.SUBSCRIPTION_EXHAUSTED)

    def test_revert_restores_balance(self):
        SubscriptionService.consume(self.child.id, self.lesson_id, self.ballet.id)
        reverted = SubscriptionService.revert(self.child.id, self.lesson_id)
        self.assertTrue(reverted)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.sessions_remaining_cache, 8)

    def test_revert_noop_if_not_consumed(self):
        self.assertFalse(SubscriptionService.revert(self.child.id, uuid.uuid4()))


class PickSubscriptionTests(SubscriptionFixtureMixin, TestCase):
    """TRU-130 п. 1: замороженный не заслоняет активный."""

    def test_active_wins_over_frozen_ending_earlier(self):
        self.make_subscription(
            ends_on=self.today + timedelta(days=5), status=Subscription.Status.FROZEN
        )
        result = self.consume()
        self.assertEqual(result.outcome, ConsumeOutcome.CONSUMED)
        self.assertEqual(result.subscription_id, self.sub.id)

    def test_frozen_reported_only_without_active(self):
        frozen = self.make_subscription(
            ends_on=self.today + timedelta(days=5), status=Subscription.Status.FROZEN
        )
        self.sub.status = Subscription.Status.EXPIRED
        self.sub.save(update_fields=["status"])
        result = self.consume()
        self.assertEqual(result.outcome, ConsumeOutcome.SUBSCRIPTION_FROZEN)
        self.assertEqual(result.subscription_id, frozen.id)

    def test_earlier_ending_active_is_used_first(self):
        earlier = self.make_subscription(ends_on=self.today + timedelta(days=5))
        self.assertEqual(self.consume().subscription_id, earlier.id)

    def test_exhausted_active_does_not_block_next_active(self):
        # Ночная задача ещё не перевела первый в «исчерпан», а новый уже куплен.
        earlier = self.make_subscription(sessions=1, ends_on=self.today + timedelta(days=5))
        self.consume()
        result = self.consume()
        self.assertEqual(result.outcome, ConsumeOutcome.CONSUMED)
        self.assertEqual(result.subscription_id, self.sub.id)
        earlier.refresh_from_db()
        self.assertEqual(earlier.sessions_remaining_cache, 0)


class SubscriptionDatesTests(SubscriptionFixtureMixin, TestCase):
    """TRU-130 п. 2: списываем, только если starts_on ≤ дата занятия ≤ ends_on."""

    def test_ended_but_still_active_is_not_consumed(self):
        self.sub.starts_on = self.today - timedelta(days=35)
        self.sub.ends_on = self.today - timedelta(days=5)
        self.sub.save(update_fields=["starts_on", "ends_on"])
        result = self.consume()
        self.assertEqual(result.outcome, ConsumeOutcome.NO_ACTIVE_SUBSCRIPTION)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.sessions_remaining_cache, 8)

    def test_not_started_yet_is_not_consumed(self):
        self.sub.starts_on = self.today + timedelta(days=3)
        self.sub.save(update_fields=["starts_on"])
        self.assertEqual(self.consume().outcome, ConsumeOutcome.NO_ACTIVE_SUBSCRIPTION)

    def test_lesson_date_decides_not_marking_day(self):
        # Отметку за вчерашнее занятие ставят сегодня, абонемент закончился вчера.
        yesterday = self.today - timedelta(days=1)
        self.sub.starts_on = self.today - timedelta(days=30)
        self.sub.ends_on = yesterday
        self.sub.save(update_fields=["starts_on", "ends_on"])
        self.assertEqual(self.consume(lesson_date=yesterday).outcome, ConsumeOutcome.CONSUMED)
        self.assertEqual(
            self.consume(lesson_date=self.today).outcome,
            ConsumeOutcome.NO_ACTIVE_SUBSCRIPTION,
        )

    def test_boundary_days_are_included(self):
        self.assertEqual(
            self.consume(lesson_date=self.sub.starts_on).outcome, ConsumeOutcome.CONSUMED
        )
        self.assertEqual(
            self.consume(lesson_date=self.sub.ends_on).outcome, ConsumeOutcome.CONSUMED
        )

    def test_frozen_outside_dates_is_not_reported(self):
        self.sub.status = Subscription.Status.FROZEN
        self.sub.starts_on = self.today - timedelta(days=35)
        self.sub.ends_on = self.today - timedelta(days=5)
        self.sub.save(update_fields=["status", "starts_on", "ends_on"])
        self.assertEqual(self.consume().outcome, ConsumeOutcome.NO_ACTIVE_SUBSCRIPTION)


class RevertTests(SubscriptionFixtureMixin, TestCase):
    """TRU-130 п. 4 и отдельный вид записи журнала для отката."""

    def test_revert_reactivates_exhausted(self):
        sub = self.make_subscription(sessions=1, ends_on=self.today + timedelta(days=5))
        self.consume(self.lesson_id)
        sub.status = Subscription.Status.EXHAUSTED  # как сделала бы ночная задача
        sub.save(update_fields=["status"])

        self.assertTrue(SubscriptionService.revert(self.child.id, self.lesson_id))

        sub.refresh_from_db()
        self.assertEqual(sub.sessions_remaining_cache, 1)
        self.assertEqual(sub.status, Subscription.Status.ACTIVE)
        self.assertEqual(self.consume().subscription_id, sub.id)

    def test_revert_keeps_other_statuses(self):
        self.consume(self.lesson_id)
        self.sub.status = Subscription.Status.EXPIRED
        self.sub.save(update_fields=["status"])
        SubscriptionService.revert(self.child.id, self.lesson_id)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.EXPIRED)

    def test_exhausted_to_active_stays_forbidden_outside_revert(self):
        self.sub.status = Subscription.Status.EXHAUSTED
        self.assertFalse(self.sub.can_transition_to(Subscription.Status.ACTIVE))

    def test_revert_writes_own_ledger_kind(self):
        self.consume(self.lesson_id)
        SubscriptionService.revert(self.child.id, self.lesson_id)
        entry = self.sub.ledger_entries.order_by("created_at").last()
        self.assertEqual(entry.kind, SubscriptionLedgerEntry.Kind.LESSON_REVERT)
        self.assertEqual(entry.delta, 1)
        self.assertFalse(
            self.sub.ledger_entries.filter(
                kind=SubscriptionLedgerEntry.Kind.MANUAL_ADJUSTMENT
            ).exists()
        )


class ConsumeRaceTests(SubscriptionFixtureMixin, TransactionTestCase):
    """TRU-130 п. 3: два одновременных consume на последнем занятии.

    Первый поток останавливается после выбора абонемента (в _check_type_rules),
    пока второй пытается списать. Без блокировки строки второй успевает
    списать то же последнее занятие, и остаток уходит в −1."""

    def test_last_session_is_consumed_once(self):
        self.sub.delete()
        last = self.make_subscription(sessions=1)
        first_inside = threading.Event()
        release = threading.Event()
        calls = []
        original_rules = subscription_service._check_type_rules

        def slow_rules(subscription):
            calls.append(subscription.id)
            if len(calls) == 1:
                first_inside.set()
                release.wait(5)
            return original_rules(subscription)

        results = {}

        def run(name):
            try:
                results[name] = self.consume().outcome
            finally:
                connection.close()

        with patch.object(subscription_service, "_check_type_rules", slow_rules):
            first = threading.Thread(target=run, args=("first",))
            first.start()
            self.assertTrue(first_inside.wait(5))
            second = threading.Thread(target=run, args=("second",))
            second.start()
            second.join(1)  # с блокировкой второй ждёт первого в базе
            release.set()
            first.join(5)
            second.join(5)

        self.assertEqual(
            sorted(o.value for o in results.values()),
            [ConsumeOutcome.CONSUMED.value, ConsumeOutcome.SUBSCRIPTION_EXHAUSTED.value],
        )
        last.refresh_from_db()
        self.assertEqual(last.sessions_remaining_cache, 0)
        self.assertEqual(LessonConsumption.objects.filter(subscription=last).count(), 1)
