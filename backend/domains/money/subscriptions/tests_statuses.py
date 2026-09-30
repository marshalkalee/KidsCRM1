from datetime import UTC, date, datetime, timedelta
from unittest import mock

from django.test import TestCase

from domains.people.clients.models import Child
from domains.platform.core.utils import today_for_org
from domains.platform.tenants.models import Direction, Organization

from .models import Subscription, SubscriptionLedgerEntry
from .renewals import expiring_child_ids
from .serializers import SubscriptionSerializer
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


class OneEndingSoonRuleTests(TestCase):
    """TRU-62: «заканчивается» одинаково в карточке, списке детей и продлениях,
    и считается по дате центра, а не сервера."""

    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.ballet = Direction.objects.create(organization=self.org, name="Балет")
        self.type = create_type(
            self.org,
            name="8 занятий",
            price=25000,
            quota_sessions=8,
            duration_days=30,
            directions=[self.ballet],
        )

    def make(self, name, *, ends_on, sessions_left, status=Subscription.Status.ACTIVE):
        child = Child.objects.create(
            organization=self.org, full_name=name, birth_date=date(2018, 1, 1)
        )
        sub = Subscription.objects.create(
            organization=self.org,
            child=child,
            subscription_type_version=self.type.versions.latest(),
            direction=self.ballet,
            starts_on=ends_on - timedelta(days=30),
            ends_on=ends_on,
            list_price=25000,
            price=25000,
            status=status,
        )
        add_ledger_entry(sub, kind=SubscriptionLedgerEntry.Kind.INITIAL_GRANT, delta=sessions_left)
        return sub

    def test_card_and_list_filter_agree(self):
        today = today_for_org(self.org)
        subs = [
            self.make("По дням", ends_on=today + timedelta(days=7), sessions_left=8),
            self.make("Граница+1", ends_on=today + timedelta(days=8), sessions_left=8),
            self.make("По занятиям", ends_on=today + timedelta(days=30), sessions_left=3),
            self.make("Занятий хватает", ends_on=today + timedelta(days=30), sessions_left=4),
            self.make(
                "Заморожен",
                ends_on=today + timedelta(days=2),
                sessions_left=1,
                status=Subscription.Status.FROZEN,
            ),
        ]
        in_list = {row["child_id"] for row in expiring_child_ids(self.org)}
        for sub in subs:
            with self.subTest(sub.child.full_name):
                self.assertEqual(
                    get_display_status(sub) == ENDING_SOON,
                    sub.child_id in in_list,
                )
        self.assertEqual(len(in_list), 2)

    def test_uses_center_date_not_server_date(self):
        # 20:00 UTC 29.09 — в Алматы уже 01:00 30.09.
        evening_utc = datetime(2026, 9, 29, 20, 0, tzinfo=UTC)
        sub = self.make("Истёк вчера", ends_on=date(2026, 9, 29), sessions_left=5)
        with mock.patch("django.utils.timezone.now", return_value=evening_utc):
            self.assertEqual(today_for_org(self.org), date(2026, 9, 30))
            update_all_subscription_statuses()
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.Status.EXPIRED)

    def test_api_shows_ending_soon(self):
        sub = self.make(
            "Скоро конец", ends_on=today_for_org(self.org) + timedelta(days=2), sessions_left=8
        )
        data = SubscriptionSerializer(sub).data
        self.assertEqual(data["status"], "active")
        self.assertEqual(data["display_status"], ENDING_SOON)
        self.assertEqual(data["display_status_label"], "Заканчивается")
