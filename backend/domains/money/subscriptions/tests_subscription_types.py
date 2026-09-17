from django.test import TestCase

from domains.platform.tenants.models import Organization
from .models import SubscriptionType
from .subscription_types import get_selectable_subscription_types, update_rules


class SubscriptionTypeVersioningTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.st = SubscriptionType.objects.create(
            organization=self.org, name="8 занятий", price=25000,
            quota_sessions=8, duration_days=30,
        )

    def test_update_rules_creates_new_version_and_keeps_old_unchanged(self):
        v1 = update_rules(self.st, price=25000, rules={"freezes_per_year": 1})
        v2 = update_rules(self.st, price=27000, rules={"freezes_per_year": 2})

        v1.refresh_from_db()
        self.assertEqual(v1.price, 25000)  # старая версия не поменялась
        self.assertEqual(v2.price, 27000)
        self.assertEqual(self.st.versions.count(), 2)

    def test_archived_type_excluded_from_selectable(self):
        self.st.is_active = False
        self.st.save(update_fields=["is_active"])

        self.assertNotIn(self.st, get_selectable_subscription_types(self.org))
        self.assertTrue(SubscriptionType.objects.for_tenant(self.org).filter(pk=self.st.pk).exists())

    def test_unlimited_xor_quota_constraint(self):
        with self.assertRaises(Exception):
            SubscriptionType.objects.create(
                organization=self.org, name="Безлимит", price=50000,
                is_unlimited=True, quota_sessions=8, duration_days=30,
            )