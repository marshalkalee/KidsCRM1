from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APITestCase

from domains.people.clients.models import Child
from domains.platform.tenants.models import Direction, Organization
from domains.platform.users.models import User

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


class RecomputeApiTests(APITestCase):
    """TRU-61: ручной пересчёт по кнопке и отчёт о расхождениях."""

    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        ballet = Direction.objects.create(organization=self.org, name="Балет")
        child = Child.objects.create(
            organization=self.org, full_name="Иванов Алихан", birth_date=date(2018, 1, 1)
        )
        st = create_type(
            self.org,
            name="8 занятий",
            price=25000,
            quota_sessions=8,
            duration_days=30,
            directions=[ballet],
        )
        self.sub = Subscription.objects.create(
            organization=self.org,
            child=child,
            subscription_type_version=st.versions.latest(),
            direction=ballet,
            starts_on=date.today(),
            ends_on=date.today() + timedelta(days=30),
            list_price=25000,
            price=25000,
        )
        add_ledger_entry(self.sub, kind=SubscriptionLedgerEntry.Kind.INITIAL_GRANT, delta=8)
        add_ledger_entry(self.sub, kind=SubscriptionLedgerEntry.Kind.CONSUMPTION, delta=-1)
        self.admin = self.user("+77010000001", User.Role.ADMIN)
        self.owner = self.user("+77010000002", User.Role.OWNER)

    def user(self, phone, role):
        return User.objects.create_user(
            phone=phone, password="x", full_name=role, organization=self.org, role=role
        )

    def url(self, suffix):
        return f"/api/v1/subscriptions/{suffix}"

    def test_recompute_fixes_broken_cache_and_reports_it(self):
        Subscription.objects.filter(pk=self.sub.pk).update(sessions_remaining_cache=3)
        self.client.force_authenticate(self.admin)
        response = self.client.post(self.url(f"{self.sub.pk}/recompute/"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.data["before"], response.data["after"]), (3, 7))
        self.assertTrue(response.data["fixed"])
        self.assertEqual(response.data["subscription"]["sessions_remaining_cache"], 7)
        self.assertEqual(BalanceDiscrepancy.objects.get().recomputed_value, 7)

        self.client.force_authenticate(self.owner)
        report = self.client.get(self.url("discrepancies/"))
        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.data[0]["cached_value"], 3)
        self.assertEqual(report.data[0]["child_name"], "Иванов Алихан")

    def test_recompute_when_cache_is_right(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post(self.url(f"{self.sub.pk}/recompute/"))
        self.assertFalse(response.data["fixed"])
        self.assertFalse(BalanceDiscrepancy.objects.exists())

    def test_report_only_for_owner_and_manager(self):
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(self.url("discrepancies/")).status_code, 403)

    def test_teacher_cannot_recompute(self):
        self.client.force_authenticate(self.user("+77010000003", User.Role.TEACHER))
        response = self.client.post(self.url(f"{self.sub.pk}/recompute/"))
        self.assertEqual(response.status_code, 403)
