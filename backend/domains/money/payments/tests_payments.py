from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from domains.money.subscriptions.models import Subscription
from domains.money.subscriptions.subscription_types import create_type
from domains.people.clients.models import Child
from domains.platform.core.audit import AuditLog
from domains.platform.tenants.models import Direction, Organization
from domains.platform.users.models import User

from .models import Payment
from .services import cancel_payment, record_payment


class PaymentTests(TestCase):
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
        self.teacher = User.objects.create_user(
            phone="77004445566",
            password="pass",
            full_name="Препод",
            organization=self.org,
            role=User.Role.TEACHER,
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

    def test_all_four_methods(self):
        for method in Payment.Method.values:
            payment = record_payment(
                actor=self.admin, subscription=self.sub, amount=1000, method=method
            )
            self.assertEqual(payment.method, method)

    def test_amount_precision_no_float_drift(self):
        payment = record_payment(
            actor=self.admin,
            subscription=self.sub,
            amount=Decimal("14999.6"),
            method=Payment.Method.CASH,
        )
        self.assertEqual(
            payment.amount, Decimal("15000")
        )  # округление до целого тенге, не float-мусор

    def test_cancel_soft_deletes_visible_in_history(self):
        payment = record_payment(
            actor=self.admin,
            subscription=self.sub,
            amount=25000,
            method=Payment.Method.KASPI_TRANSFER,
        )
        cancel_payment(payment, actor=self.admin, reason="Ошибка ввода")

        self.assertTrue(Payment.objects.all_with_deleted().filter(pk=payment.pk).exists())
        self.assertFalse(Payment.objects.for_tenant(self.org).filter(pk=payment.pk).exists())
        payment.refresh_from_db()
        self.assertIsNotNone(payment.deleted_at)
        self.assertEqual(payment.cancelled_reason, "Ошибка ввода")

    def test_cancel_recorded_in_audit_log(self):
        payment = record_payment(
            actor=self.admin, subscription=self.sub, amount=25000, method=Payment.Method.CASH
        )
        cancel_payment(payment, actor=self.admin, reason="Дубль")
        log = AuditLog.objects.filter(object_id=payment.pk, action=AuditLog.Action.DELETE).first()
        self.assertIsNotNone(log)

    def test_teacher_cannot_view_payments(self):
        record_payment(
            actor=self.admin, subscription=self.sub, amount=25000, method=Payment.Method.CASH
        )
        client = APIClient()
        client.force_authenticate(user=self.teacher)
        response = client.get("/api/v1/payments/")
        self.assertEqual(response.status_code, 403)
