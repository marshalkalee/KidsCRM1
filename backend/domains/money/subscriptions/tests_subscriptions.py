from datetime import date, timedelta

from django.test import TestCase

from domains.people.clients.models import Child
from domains.platform.tenants.models import Direction, Organization

from .models import Subscription, SubscriptionLedgerEntry
from .subscription_types import create_type, update_rules
from .subscriptions import (
    add_ledger_entry,
    get_active_subscription_for_direction,
    recompute_sessions_remaining,
    transition_status,
)


class SubscriptionTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.ballet = Direction.objects.create(organization=self.org, name="Балет")
        self.gym = Direction.objects.create(organization=self.org, name="Гимнастика")
        self.child = Child.objects.create(
            organization=self.org,
            full_name="Иванов Алихан",
            birth_date=date(2018, 1, 1),
            gender=Child.Gender.MALE,
        )
        st = create_type(
            self.org,
            name="8 занятий балета",
            price=25000,
            quota_sessions=8,
            duration_days=30,
            directions=[self.ballet],
        )
        self.sub = Subscription.objects.create(
        organization=self.org, child=self.child, subscription_type_version=st.versions.latest(),
        direction=self.ballet, starts_on=date.today(), ends_on=date.today() + timedelta(days=30),
        list_price=25000, price=25000,
        )
        add_ledger_entry(self.sub, kind=SubscriptionLedgerEntry.Kind.INITIAL_GRANT, delta=8)

    def test_recompute_matches_cache(self):
        add_ledger_entry(self.sub, kind=SubscriptionLedgerEntry.Kind.CONSUMPTION, delta=-1)
        self.sub.refresh_from_db()
        self.assertEqual(recompute_sessions_remaining(self.sub), self.sub.sessions_remaining_cache)
        self.assertEqual(self.sub.sessions_remaining_cache, 7)

    def test_rules_frozen_at_purchase(self):
        version = self.sub.subscription_type_version
        update_rules(version.subscription_type, price=30000, rules={"freezes_per_year": 1})
        version.refresh_from_db()
        self.assertEqual(version.price, 25000)

    def test_correct_subscription_picked_by_direction(self):
        gym_type = create_type(
            self.org,
            name="8 занятий гимнастики",
            price=20000,
            quota_sessions=8,
            duration_days=30,
            directions=[self.gym],
        )
        gym_sub = Subscription.objects.create(
            organization=self.org, child=self.child, subscription_type_version=gym_type.versions.latest(),
            direction=self.gym, starts_on=date.today(), ends_on=date.today() + timedelta(days=30),
            list_price=20000, price=20000,
            organization=self.org,
            child=self.child,
            subscription_type_version=gym_type.versions.latest(),
            direction=self.gym,
            starts_on=date.today(),
            ends_on=date.today() + timedelta(days=30),
        )
        self.assertEqual(get_active_subscription_for_direction(self.child, self.ballet), self.sub)
        self.assertEqual(get_active_subscription_for_direction(self.child, self.gym), gym_sub)

    def test_status_transitions(self):
        transition_status(self.sub, Subscription.Status.EXPIRED)
        with self.assertRaises(ValueError):
            transition_status(self.sub, Subscription.Status.ACTIVE)
