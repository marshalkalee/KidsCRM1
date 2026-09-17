from datetime import date, timedelta

from django.test import TestCase

from domains.money.payments.models import Payment
from domains.people.clients.models import Child
from domains.platform.core.audit import AuditLog
from domains.platform.tenants.models import Direction, Organization
from domains.platform.users.models import User

from .models import Subscription
from .sales import sell_subscription
from .subscription_types import create_type


class SellSubscriptionTests(TestCase):
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

    def _sell(self, **overrides):
        kwargs = dict(
            actor=self.admin,
            child=self.child,
            subscription_type_version=self.st.versions.latest(),
            direction=self.ballet,
            starts_on=date.today(),
            ends_on=date.today() + timedelta(days=30),
            paid_amount=25000,
            payment_method=Payment.Method.KASPI_TRANSFER,
        )
        kwargs.update(overrides)
        return sell_subscription(**kwargs)

    def test_discount_without_reason_rejected(self):
        with self.assertRaises(ValueError):
            self._sell(discount_amount=2000, paid_amount=23000)

    def test_sold_subscription_active_with_sessions(self):
        sub, payment = self._sell()
        self.assertEqual(sub.status, Subscription.Status.ACTIVE)
        self.assertEqual(sub.sessions_remaining_cache, 8)
        self.assertEqual(payment.amount, 25000)

    def test_discount_with_reason_applied(self):
        sub, _ = self._sell(
            discount_amount=5000,
            discount_reason=Subscription.DiscountReason.SECOND_CHILD,
            paid_amount=20000,
        )
        self.assertEqual(sub.price, 20000)

    def test_audit_log_created(self):
        sub, _ = self._sell()
        log = AuditLog.objects.filter(object_id=sub.pk).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.action, AuditLog.Action.CREATE)
        self.assertIn("discount_reason", log.after)
