from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APITestCase

from domains.people.clients.models import Child
from domains.platform.core.audit import AuditLog
from domains.platform.tenants.models import Direction, Organization
from domains.platform.users.models import User

from .freezes import freeze_subscription, unfreeze_subscription
from .models import Subscription, SubscriptionFreeze
from .subscription_types import create_type, update_rules


class FreezeTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.ballet = Direction.objects.create(organization=self.org, name="Балет")
        self.child = Child.objects.create(
            organization=self.org,
            full_name="Иванов Алихан",
            birth_date=date(2018, 1, 1),
            gender=Child.Gender.MALE,
        )
        self.admin = User.objects.create_user(
            phone="77001112233",
            password="pass",
            full_name="Админ",
            organization=self.org,
            role=User.Role.ADMIN,
        )
        self.st = create_type(
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
            subscription_type_version=self.st.versions.latest(),
            direction=self.ballet,
            starts_on=date.today(),
            ends_on=date.today() + timedelta(days=30),
            list_price=25000,
            price=25000,
        )

    def test_freeze_extends_end_date_by_14_days(self):
        original_end = self.sub.ends_on
        freeze_subscription(
            self.sub,
            actor=self.admin,
            starts_on=date.today(),
            ends_on=date.today() + timedelta(days=14),
            reason="Болезнь",
        )
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.ends_on, original_end + timedelta(days=14))
        self.assertEqual(self.sub.status, Subscription.Status.FROZEN)

    def test_freeze_limit_exceeded_raises(self):
        update_rules(self.st, price=25000, rules={"freezes_per_year": 1})
        self.sub.subscription_type_version = self.st.versions.latest()
        self.sub.save()

        freeze_subscription(
            self.sub,
            actor=self.admin,
            starts_on=date.today(),
            ends_on=date.today() + timedelta(days=5),
        )
        unfreeze_subscription(self.sub, actor=self.admin)

        with self.assertRaises(ValueError):
            freeze_subscription(
                self.sub,
                actor=self.admin,
                starts_on=date.today(),
                ends_on=date.today() + timedelta(days=5),
            )

    def test_early_unfreeze_recalculates(self):
        original_end = self.sub.ends_on
        freeze_subscription(
            self.sub,
            actor=self.admin,
            starts_on=date.today(),
            ends_on=date.today() + timedelta(days=14),
        )
        unfreeze_subscription(
            self.sub, actor=self.admin, actual_end_date=date.today() + timedelta(days=5)
        )

        self.sub.refresh_from_db()
        self.assertEqual(self.sub.ends_on, original_end + timedelta(days=5))
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)

    def test_freeze_recorded_in_audit_log(self):
        freeze_subscription(
            self.sub,
            actor=self.admin,
            starts_on=date.today(),
            ends_on=date.today() + timedelta(days=14),
        )
        log = AuditLog.objects.filter(object_id=self.sub.pk, action=AuditLog.Action.FREEZE).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.actor, self.admin)


class FreezeApiTests(APITestCase):
    """TRU-63: API заморозки с понятными ошибками и история заморозок."""

    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        ballet = Direction.objects.create(organization=self.org, name="Балет")
        child = Child.objects.create(
            organization=self.org, full_name="Иванов Алихан", birth_date=date(2018, 1, 1)
        )
        self.admin = User.objects.create_user(
            phone="77001112233",
            password="pass",
            full_name="Админ",
            organization=self.org,
            role=User.Role.ADMIN,
        )
        self.type = create_type(
            self.org,
            name="8 занятий",
            price=25000,
            quota_sessions=8,
            duration_days=30,
            directions=[ballet],
        )
        self.today = date.today()
        self.sub = Subscription.objects.create(
            organization=self.org,
            child=child,
            subscription_type_version=self.type.versions.latest(),
            direction=ballet,
            starts_on=self.today - timedelta(days=5),
            ends_on=self.today + timedelta(days=25),
            list_price=25000,
            price=25000,
        )
        self.client.force_authenticate(self.admin)

    def freeze(self, **payload):
        return self.client.post(f"/api/v1/subscriptions/{self.sub.pk}/freeze/", payload)

    def unfreeze(self, **payload):
        return self.client.post(f"/api/v1/subscriptions/{self.sub.pk}/unfreeze/", payload)

    def test_freeze_moves_end_and_shows_history(self):
        response = self.freeze(
            starts_on=self.today.isoformat(),
            ends_on=(self.today + timedelta(days=14)).isoformat(),
            reason="Болезнь",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "frozen")
        self.assertEqual(response.data["ends_on"], (self.today + timedelta(days=39)).isoformat())
        self.assertEqual(len(response.data["freezes"]), 1)
        self.assertEqual(response.data["freezes"][0]["reason"], "Болезнь")
        self.assertEqual(response.data["freezes"][0]["days"], 14)

        listed = self.client.get("/api/v1/subscriptions/", {"child_id": self.sub.child_id})
        self.assertEqual(listed.data["results"][0]["freezes"][0]["days"], 14)

    def test_bad_dates_are_field_errors(self):
        response = self.freeze(starts_on=self.today.isoformat(), ends_on=self.today.isoformat())
        self.assertEqual(response.status_code, 400)
        self.assertIn("ends_on", response.data)
        self.assertEqual(self.freeze(starts_on="вчера", ends_on="").status_code, 400)

    def test_limit_exceeded_is_readable(self):
        update_rules(self.type, price=25000, rules={"freezes_per_year": 1})
        self.sub.subscription_type_version = self.type.versions.latest()
        self.sub.save()
        SubscriptionFreeze.objects.create(
            organization=self.org,
            subscription=self.sub,
            starts_on=self.today - timedelta(days=60),
            ends_on=self.today - timedelta(days=50),
        )
        response = self.freeze(
            starts_on=self.today.isoformat(), ends_on=(self.today + timedelta(days=7)).isoformat()
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("лимит", response.data["detail"])

    def test_cannot_freeze_expired(self):
        Subscription.objects.filter(pk=self.sub.pk).update(status=Subscription.Status.EXPIRED)
        response = self.freeze(
            starts_on=self.today.isoformat(), ends_on=(self.today + timedelta(days=7)).isoformat()
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("действующий", response.data["detail"])

    def test_early_unfreeze_today_returns_unused_days(self):
        freeze_subscription(
            self.sub,
            actor=self.admin,
            starts_on=self.today - timedelta(days=3),
            ends_on=self.today + timedelta(days=11),
        )
        response = self.unfreeze()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "active")
        # Заморозка длилась 3 дня из 14 — срок сдвинут только на 3.
        self.assertEqual(response.data["ends_on"], (self.today + timedelta(days=28)).isoformat())
        self.assertEqual(response.data["freezes"][0]["days"], 3)

    def test_unfreeze_not_frozen(self):
        response = self.unfreeze()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["detail"], "Абонемент не заморожен.")
