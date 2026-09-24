import uuid
from datetime import date, timedelta

from django.test import TestCase

from domains.money.subscriptions.models import Subscription
from domains.money.subscriptions.subscription_types import create_type
from domains.people.clients.models import Child
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User

from .models import Payment
from .services import record_payment


class PaymentIdempotencyTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.branch = Branch.objects.create(organization=self.org, name="Филиал на Абая")
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
            branch=self.branch,
            starts_on=date.today(),
            ends_on=date.today() + timedelta(days=30),
            list_price=25000,
            price=25000,
        )

    def test_double_submit_same_key_creates_one_payment(self):
        key = str(uuid.uuid4())
        p1 = record_payment(
            actor=self.admin,
            subscription=self.sub,
            amount=25000,
            method=Payment.Method.CASH,
            idempotency_key=key,
        )
        p2 = record_payment(
            actor=self.admin,
            subscription=self.sub,
            amount=25000,
            method=Payment.Method.CASH,
            idempotency_key=key,
        )
        self.assertEqual(p1.pk, p2.pk)
        self.assertEqual(Payment.objects.filter(provider_transaction_id=key).count(), 1)

    def test_different_keys_create_separate_payments(self):
        record_payment(
            actor=self.admin,
            subscription=self.sub,
            amount=10000,
            method=Payment.Method.CASH,
            idempotency_key=str(uuid.uuid4()),
        )
        record_payment(
            actor=self.admin,
            subscription=self.sub,
            amount=10000,
            method=Payment.Method.CASH,
            idempotency_key=str(uuid.uuid4()),
        )
        self.assertEqual(Payment.objects.filter(subscription=self.sub).count(), 2)
