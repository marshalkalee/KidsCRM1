from datetime import date, timedelta

from django.test import TestCase

from domains.people.clients.models import Child
from domains.platform.tenants.models import Direction, Organization

from .models import BalanceDiscrepancy, Subscription, SubscriptionFreeze, SubscriptionLedgerEntry
from .reconciliation import manual_recompute, reconcile_all_active_subscriptions
from .subscription_types import create_type
from .subscriptions import add_ledger_entry


class ReconciliationTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.ballet = Direction.objects.create(organization=self.org, name="Балет")
        self.child = Child.objects.create(
            organization=self.org,
            full_name="Иванов Алихан",
            birth_date=date(2018, 1, 1),
            gender=Child.Gender.MALE,
        )
        st = create_type(
            self.org,
            name="8 занятий",
            price=25000,
            quota_sessions=8,
            duration_days=30,
            directions=[self.ballet],
        )
        self.sub = Subscription.objects.create(
            organization=self.org,
            child=self.child,
            subscription_type_version=st.versions.latest(),
            direction=self.ballet,
            starts_on=date.today(),
            ends_on=date.today() + timedelta(days=30),
            list_price=25000,
            price=25000,
        )
        add_ledger_entry(self.sub, kind=SubscriptionLedgerEntry.Kind.INITIAL_GRANT, delta=8)

    def test_broken_cache_fixed_by_reconciliation(self):
        self.sub.sessions_remaining_cache = 99  # искусственно портим
        self.sub.save(update_fields=["sessions_remaining_cache"])

        found = reconcile_all_active_subscriptions()

        self.assertEqual(found, 1)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.sessions_remaining_cache, 8)
        discrepancy = BalanceDiscrepancy.objects.get(subscription=self.sub)
        self.assertEqual(discrepancy.cached_value, 99)
        self.assertEqual(discrepancy.recomputed_value, 8)

    def test_no_discrepancy_no_log_entry(self):
        reconcile_all_active_subscriptions()
        self.assertFalse(BalanceDiscrepancy.objects.filter(subscription=self.sub).exists())

    def test_recompute_with_freeze_and_two_makeups(self):
        SubscriptionFreeze.objects.create(
            organization=self.org,
            subscription=self.sub,
            starts_on=date.today(),
            ends_on=date.today() + timedelta(days=5),
        )
        add_ledger_entry(self.sub, kind=SubscriptionLedgerEntry.Kind.CONSUMPTION, delta=-1)
        add_ledger_entry(
            self.sub, kind=SubscriptionLedgerEntry.Kind.CONSUMPTION, delta=-1, comment="отработка"
        )
        add_ledger_entry(
            self.sub, kind=SubscriptionLedgerEntry.Kind.CONSUMPTION, delta=-1, comment="отработка"
        )

        self.sub.refresh_from_db()
        self.assertEqual(self.sub.sessions_remaining_cache, 5)

    def test_manual_recompute_button(self):
        self.sub.sessions_remaining_cache = 0
        self.sub.save(update_fields=["sessions_remaining_cache"])
        result = manual_recompute(self.sub)
        self.assertEqual(result, 8)
