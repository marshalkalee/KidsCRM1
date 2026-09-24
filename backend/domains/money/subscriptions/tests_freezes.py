from datetime import date, timedelta

from django.test import TestCase

from domains.people.clients.models import Child
from domains.platform.core.audit import AuditLog
from domains.platform.tenants.models import Direction, Organization
from domains.platform.users.models import User

from .freezes import freeze_subscription, unfreeze_subscription
from .models import Subscription
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
