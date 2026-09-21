"""
expiring_child_ids() — единая точка правды "абонемент скоро заканчивается"
для фильтра списка детей (people/clients) и будущего экрана «Продления».
Порог читается из org_settings, не подставляется числом здесь.
"""

from datetime import date, timedelta

from django.test import TestCase

from domains.people.clients.models import Child
from domains.platform.tenants.models import Direction, Organization
from domains.platform.tenants.org_settings import (
    SUBSCRIPTION_ENDING_DAYS_THRESHOLD,
    SUBSCRIPTION_ENDING_LESSONS_THRESHOLD,
)

from .models import Subscription
from .renewals import expiring_child_ids
from .subscription_types import create_type

TODAY = date(2026, 9, 21)


class ExpiringChildIdsTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.ballet = Direction.objects.create(organization=self.org, name="Балет")
        self.limited_type = create_type(
            self.org, name="8 занятий", price=25000, quota_sessions=8, duration_days=30
        )
        self.unlimited_type = create_type(
            self.org, name="Безлимит", price=40000, is_unlimited=True, duration_days=30
        )

    def _make_child(self, name):
        return Child.objects.create(
            organization=self.org,
            full_name=name,
            birth_date=date(2018, 1, 1),
            gender=Child.Gender.MALE,
        )

    def _make_subscription(
        self,
        child,
        *,
        version=None,
        status=Subscription.Status.ACTIVE,
        ends_on,
        sessions_remaining_cache=None,
    ):
        version = version or self.limited_type.versions.latest()
        return Subscription.objects.create(
            organization=self.org,
            child=child,
            subscription_type_version=version,
            direction=self.ballet,
            starts_on=TODAY - timedelta(days=10),
            ends_on=ends_on,
            status=status,
            list_price=version.price,
            price=version.price,
            sessions_remaining_cache=sessions_remaining_cache,
        )

    def _expiring_ids(self):
        return set(expiring_child_ids(self.org, today=TODAY).values_list("child_id", flat=True))

    def test_active_subscription_ending_within_days_threshold_is_expiring(self):
        child = self._make_child("Скоро истечёт")
        # Дефолтный порог дней — 7 (DEFAULT_ORG_SETTINGS).
        self._make_subscription(
            child, ends_on=TODAY + timedelta(days=3), sessions_remaining_cache=8
        )

        self.assertIn(child.id, self._expiring_ids())

    def test_active_subscription_far_from_ending_is_not_expiring(self):
        child = self._make_child("Далеко до конца")
        self._make_subscription(
            child, ends_on=TODAY + timedelta(days=60), sessions_remaining_cache=8
        )

        self.assertNotIn(child.id, self._expiring_ids())

    def test_low_sessions_remaining_counts_as_expiring_even_if_date_is_far(self):
        child = self._make_child("Мало занятий")
        # Дефолтный порог занятий — 3.
        self._make_subscription(
            child, ends_on=TODAY + timedelta(days=60), sessions_remaining_cache=2
        )

        self.assertIn(child.id, self._expiring_ids())

    def test_unlimited_subscription_ignores_lessons_threshold(self):
        child = self._make_child("Безлимит")
        self._make_subscription(
            child,
            version=self.unlimited_type.versions.latest(),
            ends_on=TODAY + timedelta(days=60),
            sessions_remaining_cache=None,
        )

        self.assertNotIn(child.id, self._expiring_ids())

    def test_frozen_subscription_is_not_expiring(self):
        child = self._make_child("Заморожен")
        self._make_subscription(
            child,
            status=Subscription.Status.FROZEN,
            ends_on=TODAY + timedelta(days=1),
            sessions_remaining_cache=1,
        )

        self.assertNotIn(child.id, self._expiring_ids())

    def test_expired_subscription_is_not_expiring(self):
        child = self._make_child("Истёк")
        self._make_subscription(
            child,
            status=Subscription.Status.EXPIRED,
            ends_on=TODAY - timedelta(days=1),
            sessions_remaining_cache=0,
        )

        self.assertNotIn(child.id, self._expiring_ids())

    def test_threshold_is_read_from_org_settings_not_hardcoded(self):
        child = self._make_child("Порог из настроек")
        self._make_subscription(
            child, ends_on=TODAY + timedelta(days=20), sessions_remaining_cache=8
        )
        self.assertNotIn(child.id, self._expiring_ids())

        self.org.settings[SUBSCRIPTION_ENDING_DAYS_THRESHOLD] = 30
        self.org.save(update_fields=["settings"])

        self.assertIn(child.id, self._expiring_ids())

    def test_lessons_threshold_is_read_from_org_settings(self):
        child = self._make_child("Порог занятий из настроек")
        self._make_subscription(
            child, ends_on=TODAY + timedelta(days=60), sessions_remaining_cache=5
        )
        self.assertNotIn(child.id, self._expiring_ids())

        self.org.settings[SUBSCRIPTION_ENDING_LESSONS_THRESHOLD] = 5
        self.org.save(update_fields=["settings"])

        self.assertIn(child.id, self._expiring_ids())

    def test_tenant_isolation(self):
        other_org = Organization.objects.create(name="Other", slug="other")
        other_ballet = Direction.objects.create(organization=other_org, name="Балет")
        other_type = create_type(
            other_org, name="8 занятий", price=25000, quota_sessions=8, duration_days=30
        )
        other_child = Child.objects.create(
            organization=other_org,
            full_name="Чужой",
            birth_date=date(2018, 1, 1),
            gender=Child.Gender.MALE,
        )
        Subscription.objects.create(
            organization=other_org,
            child=other_child,
            subscription_type_version=other_type.versions.latest(),
            direction=other_ballet,
            starts_on=TODAY - timedelta(days=10),
            ends_on=TODAY + timedelta(days=1),
            status=Subscription.Status.ACTIVE,
            list_price=25000,
            price=25000,
            sessions_remaining_cache=1,
        )

        self.assertNotIn(other_child.id, self._expiring_ids())
