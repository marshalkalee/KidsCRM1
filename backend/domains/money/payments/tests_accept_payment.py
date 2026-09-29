from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from rest_framework.test import APITestCase

from domains.money.subscriptions.models import Subscription
from domains.money.subscriptions.subscription_types import create_type
from domains.people.clients.models import Child
from domains.platform.tenants.models import Direction, Organization
from domains.platform.users.models import User

from .models import Payment
from .services import record_payment


class AcceptPaymentApiTests(APITestCase):
    """TRU-67: приём оплаты во frontend2 — двойной клик не создаёт вторую
    оплату, в ответе остаток долга."""

    def setUp(self):
        self.org, self.admin, self.sub = self.center("true-ballet", "+77010000001")

    def center(self, slug, phone):
        org = Organization.objects.create(name=slug, slug=slug)
        ballet = Direction.objects.create(organization=org, name="Балет")
        child = Child.objects.create(
            organization=org, full_name="Иванов Алихан", birth_date=date(2018, 1, 1)
        )
        st = create_type(
            org,
            name="8 занятий",
            price=30000,
            quota_sessions=8,
            duration_days=30,
            directions=[ballet],
        )
        sub = Subscription.objects.create(
            organization=org,
            child=child,
            subscription_type_version=st.versions.latest(),
            direction=ballet,
            starts_on=date.today(),
            ends_on=date.today() + timedelta(days=30),
            list_price=30000,
            price=30000,
        )
        admin = User.objects.create_user(
            phone=phone, password="x", full_name="Админ", organization=org, role=User.Role.ADMIN
        )
        return org, admin, sub

    def pay(self, key, amount="10000", user=None, sub=None):
        self.client.force_authenticate(user or self.admin)
        return self.client.post(
            "/api/v1/payments/",
            {
                "subscription": str((sub or self.sub).pk),
                "amount": amount,
                "method": "kaspi_transfer",
                "idempotency_key": str(key),
            },
        )

    def test_double_click_creates_one_payment(self):
        key = uuid4()
        first = self.pay(key)
        second = self.pay(key)
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(Payment.objects.count(), 1)

    def test_response_has_remaining_debt(self):
        response = self.pay(uuid4(), amount="12500")
        self.assertEqual(response.data["subscription_debt"], "17500")
        self.assertEqual(response.data["child_debt"], "17500")
        self.assertEqual(response.data["method_display"], "Kaspi-перевод")

    def test_same_key_in_other_center_is_separate(self):
        key = uuid4()
        self.pay(key)
        _, other_admin, other_sub = self.center("other", "+77010000009")
        response = self.pay(key, user=other_admin, sub=other_sub)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Payment.objects.count(), 2)
        payment = Payment.objects.get(pk=response.data["id"])
        self.assertEqual(payment.subscription_id, other_sub.pk)

    def test_subscription_list_has_debt(self):
        record_payment(actor=self.admin, subscription=self.sub, amount=5000, method="cash")
        self.client.force_authenticate(self.admin)
        response = self.client.get("/api/v1/subscriptions/", {"child_id": self.sub.child_id})
        self.assertEqual(response.data["results"][0]["debt"], "25000")

    def test_overpaid_subscription_debt_is_zero(self):
        record_payment(actor=self.admin, subscription=self.sub, amount=35000, method="cash")
        from domains.money.subscriptions.debt import subscription_debt

        self.assertEqual(subscription_debt(self.sub), Decimal(0))

    def test_zero_amount_is_rejected(self):
        response = self.pay(uuid4(), amount="0")
        self.assertEqual(response.status_code, 400)
        self.assertIn("amount", response.data)
