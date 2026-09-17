import uuid
from datetime import date, timedelta

from django.test import TestCase

from domains.people.clients.models import Child
from domains.platform.tenants.models import Direction, Organization
from .subscription_service import ConsumeOutcome, SubscriptionService
from .subscription_types import create_type
from .models import Subscription, SubscriptionLedgerEntry
from .subscriptions import add_ledger_entry


class ConsumeTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.ballet = Direction.objects.create(organization=self.org, name="Балет")
        self.child = Child.objects.create(
            organization=self.org, full_name="Иванов Алихан",
            birth_date=date(2018, 1, 1), gender=Child.Gender.MALE,
        )
        st = create_type(self.org, name="8 занятий", price=25000,
                          quota_sessions=8, duration_days=30, directions=[self.ballet])

        self.sub = Subscription.objects.create(
            organization=self.org, child=self.child, subscription_type_version=st.versions.latest(),
            direction=self.ballet, starts_on=date.today(), ends_on=date.today() + timedelta(days=30),
            list_price=25000, price=25000,
        )
        add_ledger_entry(self.sub, kind=SubscriptionLedgerEntry.Kind.INITIAL_GRANT, delta=8)
        self.lesson_id = uuid.uuid4()

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