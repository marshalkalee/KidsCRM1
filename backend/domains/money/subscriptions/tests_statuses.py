from datetime import date, timedelta

from django.test import TestCase

from domains.people.clients.models import Child
from domains.platform.tenants.models import Direction, Organization

from .models import Subscription, SubscriptionLedgerEntry
from .statuses import ENDING_SOON, get_display_status, update_all_subscription_statuses
from .subscription_types import create_type
from .subscriptions import add_ledger_entry


class AutoStatusTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.ballet = Direction.objects.create(organization=self.org, name="Балет")
        self.child = Child.objects.create(
            organization=self.org,
            full_name="Иванов Алихан",
            birth_date=date(2018, 1, 1),
            gender=Child.Gender.MALE,
        )
        self.st = create_type(
            self.org,
            name="8 занятий",
            price=25000,
            quota_sessions=8,
            duration_days=30,
            directions=[self.ballet],
        )

    def _make_sub(self, ends_on, sessions_left):
        sub = Subscription.objects.create(
            organization=self.org,
            child=self.child,
            subscription_type_version=self.st.versions.latest(),
            direction=self.ballet,
            starts_on=date.today(),
            ends_on=ends_on,
            list_price=25000,
            price=25000,
        )
        add_ledger_entry(sub, kind=SubscriptionLedgerEntry.Kind.INITIAL_GRANT, delta=sessions_left)
        return sub

    def test_ending_soon_by_lessons_only(self):
        sub = self._make_sub(
            date.today() + timedelta(days=30), sessions_left=2
        )  # порог по умолчанию — 3
        self.assertEqual(get_display_status(sub), ENDING_SOON)

    def test_ending_soon_by_days_only(self):
        sub = self._make_sub(
            date.today() + timedelta(days=3), sessions_left=8
        )  # порог по умолчанию — 7
        self.assertEqual(get_display_status(sub), ENDING_SOON)

    def test_not_ending_soon(self):
        sub = self._make_sub(date.today() + timedelta(days=30), sessions_left=8)
        self.assertEqual(get_display_status(sub), Subscription.Status.ACTIVE)

    def test_threshold_change_affects_result_immediately(self):
        sub = self._make_sub(date.today() + timedelta(days=30), sessions_left=5)
        self.assertEqual(get_display_status(sub), Subscription.Status.ACTIVE)

        self.org.settings = {**self.org.settings, "subscription_ending_lessons_threshold": 5}
        self.org.save(update_fields=["settings"])
        sub.refresh_from_db()
        self.assertEqual(get_display_status(sub), ENDING_SOON)

    def test_expires_automatically_by_date(self):
        sub = self._make_sub(date.today() - timedelta(days=1), sessions_left=8)
        update_all_subscription_statuses()
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.Status.EXPIRED)

    def test_exhausts_automatically_by_sessions(self):
        sub = self._make_sub(date.today() + timedelta(days=30), sessions_left=1)
        add_ledger_entry(sub, kind=SubscriptionLedgerEntry.Kind.CONSUMPTION, delta=-1)
        update_all_subscription_statuses()
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.Status.EXHAUSTED)

    def test_frozen_shows_frozen_not_ending_soon(self):
        sub = self._make_sub(date.today() + timedelta(days=2), sessions_left=1)
        sub.status = Subscription.Status.FROZEN
        sub.save(update_fields=["status"])
        self.assertEqual(get_display_status(sub), Subscription.Status.FROZEN)
