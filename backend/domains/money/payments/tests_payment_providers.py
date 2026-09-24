from datetime import date, timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase

from domains.money.subscriptions.models import Subscription
from domains.money.subscriptions.subscription_types import create_type
from domains.people.clients.models import Child
from domains.platform.tenants.models import Direction, Organization
from domains.platform.users.models import User

from .models import Payment
from .services import record_payment


class PaymentProviderTests(TestCase):
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

    def test_manual_payment_confirmed_immediately(self):
        payment = record_payment(
            actor=self.admin, subscription=self.sub, amount=25000, method=Payment.Method.CASH
        )
        self.assertEqual(payment.provider, Payment.Provider.MANUAL)
        self.assertEqual(payment.status, Payment.Status.CONFIRMED)
        self.assertIsNotNone(payment.confirmed_at)
        self.assertIsNone(payment.provider_transaction_id)

    def test_two_manual_payments_no_transaction_id_conflict(self):
        record_payment(
            actor=self.admin, subscription=self.sub, amount=10000, method=Payment.Method.CASH
        )
        record_payment(
            actor=self.admin, subscription=self.sub, amount=10000, method=Payment.Method.CASH
        )
        self.assertEqual(Payment.objects.filter(provider_transaction_id__isnull=True).count(), 2)

    def test_idempotent_retrieval_by_transaction_id(self):
        payment, created = Payment.objects.get_or_create(
            provider=Payment.Provider.MANUAL,
            provider_transaction_id="TXN-123",
            defaults=dict(
                organization=self.org,
                subscription=self.sub,
                amount=25000,
                method=Payment.Method.KASPI_TRANSFER,
                received_by=self.admin,
            ),
        )
        self.assertTrue(created)

        payment_retry, created_retry = Payment.objects.get_or_create(
            provider=Payment.Provider.MANUAL,
            provider_transaction_id="TXN-123",
            defaults=dict(
                organization=self.org,
                subscription=self.sub,
                amount=99999,
                method=Payment.Method.KASPI_TRANSFER,
                received_by=self.admin,
            ),
        )
        self.assertFalse(created_retry)
        self.assertEqual(payment.pk, payment_retry.pk)
        self.assertEqual(Payment.objects.filter(provider_transaction_id="TXN-123").count(), 1)

    def test_duplicate_transaction_id_rejected_at_db_level(self):
        Payment.objects.create(
            organization=self.org,
            subscription=self.sub,
            amount=25000,
            method=Payment.Method.KASPI_TRANSFER,
            provider_transaction_id="TXN-456",
            received_by=self.admin,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Payment.objects.create(
                organization=self.org,
                subscription=self.sub,
                amount=1,
                method=Payment.Method.KASPI_TRANSFER,
                provider_transaction_id="TXN-456",
                received_by=self.admin,
            )
