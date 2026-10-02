"""
Удалённая оплата через Kaspi: счёт родителю → оплата (payments/remote.py).
Счёт не уменьшает долг, пока не оплачен; оплата по счёту создаётся одна,
сколько бы раз ни пришёл вебхук или ни нажали «Оплата пришла».
"""

import json
from datetime import date, timedelta
from uuid import uuid4

from django.test import override_settings, tag
from django.utils import timezone
from rest_framework.test import APITestCase

from domains.money.subscriptions.debt import subscription_debt
from domains.money.subscriptions.models import Subscription
from domains.money.subscriptions.subscription_types import create_type
from domains.people.clients.models import Child, ChildContact, ContactPhone, ParentContact
from domains.platform.tenants.models import Direction, Organization
from domains.platform.users.models import User

from .kaspi import FakeKaspiGateway
from .models import Payment, PaymentRequest

DETAILS = "https://pay.kaspi.kz/pay/truballet"


def center(slug, phone, details=DETAILS):
    org = Organization.objects.create(
        name="True Ballet", slug=slug, settings={"kaspi_payment_details": details}
    )
    ballet = Direction.objects.create(organization=org, name="Балет")
    child = Child.objects.create(
        organization=org, full_name="Иванов Алихан", birth_date=date(2018, 1, 1)
    )
    parent = ParentContact.objects.create(organization=org, full_name="Иванова Айгерим")
    ContactPhone.objects.create(parent_contact=parent, number="+7 701 555 44 33")
    ChildContact.objects.create(organization=org, child=child, parent_contact=parent, is_payer=True)
    st = create_type(
        org, name="8 занятий", price=30000, quota_sessions=8, duration_days=30, directions=[ballet]
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


class RemotePaymentLinkTests(APITestCase):
    """Без шлюза: сообщение с реквизитами центра, подтверждает администратор."""

    def setUp(self):
        self.org, self.admin, self.sub = center("tb-link", "+77010000001")
        self.client.force_authenticate(self.admin)

    def invoice(self, **extra):
        body = {"subscription": str(self.sub.pk), "amount": "30000", **extra}
        return self.client.post("/api/v1/payments/requests/", body, format="json")

    def test_request_does_not_reduce_debt_until_paid(self):
        response = self.invoice()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["channel"], "link")
        self.assertEqual(response.data["status"], "pending")
        self.assertEqual(response.data["phone"], "+77015554433")
        self.assertIn(DETAILS, response.data["message"])
        self.assertIn("30 000 ₸", response.data["message"])
        self.assertIn("Иванова Айгерим", response.data["message"])
        self.assertTrue(response.data["whatsapp_url"].startswith("https://wa.me/77015554433?text="))
        self.assertEqual(subscription_debt(self.sub), 30000)
        self.assertFalse(Payment.objects.exists())

    def test_confirm_creates_one_kaspi_payment(self):
        req_id = self.invoice().data["id"]
        first = self.client.post(f"/api/v1/payments/requests/{req_id}/confirm/")
        second = self.client.post(f"/api/v1/payments/requests/{req_id}/confirm/")
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(first.data["status"], "paid")
        self.assertEqual(first.data["subscription_debt"], "0")
        self.assertEqual(second.data["payment"], first.data["payment"])
        payment = Payment.objects.get()
        self.assertEqual(payment.provider, Payment.Provider.KASPI_PAY)
        self.assertEqual(payment.method, Payment.Method.KASPI_TRANSFER)
        self.assertEqual(payment.status, Payment.Status.CONFIRMED)
        self.assertEqual(payment.received_by, self.admin)

    def test_double_click_creates_one_request(self):
        key = str(uuid4())
        first = self.invoice(idempotency_key=key)
        second = self.invoice(idempotency_key=key)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(PaymentRequest.objects.count(), 1)

    def test_phone_can_be_overridden(self):
        response = self.invoice(phone="8 777 123 45 67")
        self.assertEqual(response.data["phone"], "+77771234567")

    def test_without_details_explains_where_to_set_them(self):
        self.org.settings = {}
        self.org.save()
        response = self.invoice()
        self.assertEqual(response.status_code, 400)
        self.assertIn("настройках организации", response.data["detail"])

    def test_cancel_then_confirm_is_refused(self):
        req_id = self.invoice().data["id"]
        cancelled = self.client.post(f"/api/v1/payments/requests/{req_id}/cancel/")
        self.assertEqual(cancelled.data["status"], "cancelled")
        again = self.client.post(f"/api/v1/payments/requests/{req_id}/cancel/")
        self.assertEqual(again.status_code, 400)
        confirm = self.client.post(f"/api/v1/payments/requests/{req_id}/confirm/")
        self.assertEqual(confirm.status_code, 400)
        self.assertFalse(Payment.objects.exists())

    def test_options_prefill_payer(self):
        response = self.client.get(
            "/api/v1/payments/requests/options/", {"child_id": str(self.sub.child_id)}
        )
        self.assertEqual(
            response.data,
            {
                "channel": "link",
                "ready": True,
                "details": DETAILS,
                "phone": "+77015554433",
                "parent_name": "Иванова Айгерим",
            },
        )

    def test_teacher_cannot_invoice_and_list_filters_by_child(self):
        self.invoice()
        teacher = User.objects.create_user(
            phone="+77010000009",
            password="x",
            full_name="Педагог",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        self.client.force_authenticate(teacher)
        self.assertEqual(self.invoice().status_code, 403)
        self.client.force_authenticate(self.admin)
        rows = self.client.get(
            "/api/v1/payments/requests/", {"child_id": str(self.sub.child_id)}
        ).data["results"]
        self.assertEqual(len(rows), 1)


@tag("tenant_isolation")
class RemotePaymentIsolationTests(APITestCase):
    def test_foreign_request_and_subscription_are_invisible(self):
        _org_a, admin_a, _sub_a = center("tb-a", "+77010000001")
        _org_b, admin_b, sub_b = center("tb-b", "+77010000002")
        self.client.force_authenticate(admin_b)
        req_b = self.client.post(
            "/api/v1/payments/requests/",
            {"subscription": str(sub_b.pk), "amount": "1000"},
            format="json",
        ).data["id"]
        self.client.force_authenticate(admin_a)
        self.assertEqual(self.client.get("/api/v1/payments/requests/").data["results"], [])
        self.assertEqual(
            self.client.post(f"/api/v1/payments/requests/{req_b}/confirm/").status_code, 404
        )
        foreign = self.client.post(
            "/api/v1/payments/requests/",
            {"subscription": str(sub_b.pk), "amount": "1000"},
            format="json",
        )
        self.assertEqual(foreign.status_code, 400)
        self.assertFalse(Payment.objects.exists())


@override_settings(KASPI_PAY_GATEWAY="fake", KASPI_PAY_WEBHOOK_SECRET="s3cret")
class RemotePaymentGatewayTests(APITestCase):
    """Со шлюзом: счёт уходит в Kaspi, оплату подтверждает вебхук."""

    def setUp(self):
        self.org, self.admin, self.sub = center("tb-gw", "+77010000001", details="")
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            "/api/v1/payments/requests/",
            {"subscription": str(self.sub.pk), "amount": "30000"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.req = PaymentRequest.objects.get(pk=response.data["id"])

    def webhook(self, payload, signature=None):
        body = json.dumps(payload).encode()
        self.client.force_authenticate(None)
        return self.client.post(
            "/api/v1/payments/kaspi/webhook/",
            body,
            content_type="application/json",
            HTTP_X_KASPI_SIGNATURE=signature or FakeKaspiGateway.sign(body),
        )

    def test_invoice_goes_to_gateway(self):
        self.assertEqual(self.req.channel, PaymentRequest.Channel.GATEWAY)
        self.assertTrue(self.req.external_id.startswith("fake-"))
        self.assertIn(f"/pay/test/{self.req.external_id}", self.req.pay_url)
        self.assertIn("приложение Kaspi.kz", self.req.message)
        self.assertIsNotNone(self.req.expires_at)

    def test_webhook_paid_is_idempotent(self):
        payload = {"invoice_id": self.req.external_id, "status": "paid", "transaction_id": "TX1"}
        self.assertEqual(self.webhook(payload).status_code, 200)
        self.assertEqual(self.webhook(payload).status_code, 200)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, PaymentRequest.Status.PAID)
        payment = Payment.objects.get()
        self.assertEqual(payment.provider_transaction_id, f"{self.org.pk}:TX1")
        self.assertEqual(payment.received_by, self.admin)
        self.assertEqual(subscription_debt(self.sub), 0)

    def test_webhook_with_bad_signature_is_rejected(self):
        payload = {"invoice_id": self.req.external_id, "status": "paid"}
        self.assertEqual(self.webhook(payload, signature="forged").status_code, 403)
        self.assertFalse(Payment.objects.exists())

    def test_unknown_invoice_is_acknowledged(self):
        response = self.webhook({"invoice_id": "nope", "status": "paid"})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["status"])

    def test_test_pay_page(self):
        self.client.force_authenticate(None)
        url = f"/api/v1/payments/kaspi/test-pay/{self.req.external_id}/"
        self.assertEqual(self.client.get(url).data["amount"], "30000")
        self.assertEqual(self.client.post(url).data["status"], "paid")
        self.assertEqual(self.client.post(url).status_code, 400)
        self.assertEqual(Payment.objects.count(), 1)

    def test_expired_invoice(self):
        PaymentRequest.objects.filter(pk=self.req.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        rows = self.client.get("/api/v1/payments/requests/").data["results"]
        self.assertEqual(rows[0]["status"], "expired")


class RemotePaymentOffWithoutFakeGatewayTests(APITestCase):
    def test_test_pay_and_webhook_are_closed_without_gateway(self):
        _org, admin, sub = center("tb-off", "+77010000001")
        self.client.force_authenticate(admin)
        self.client.post(
            "/api/v1/payments/requests/",
            {"subscription": str(sub.pk), "amount": "1000"},
            format="json",
        )
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post("/api/v1/payments/kaspi/webhook/", {}).status_code, 404)
        self.assertEqual(self.client.get("/api/v1/payments/kaspi/test-pay/x/").status_code, 404)
