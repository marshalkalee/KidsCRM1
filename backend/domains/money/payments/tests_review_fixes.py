"""
Исправления после ревью продажи и оплат (TRU-131):
- скидка больше цены давала отрицательную стоимость абонемента;
- фильтр оплат по родителю сравнивал с id связи ChildContact;
- одну оплату можно было отменить дважды;
- дату оплаты нельзя было указать (paid_at = момент ввода в CRM).
"""

from datetime import date, datetime, timedelta

import pytz
from django.test import TestCase, tag
from rest_framework.test import APIClient

from domains.money.subscriptions.models import Subscription
from domains.money.subscriptions.sales import sell_subscription
from domains.money.subscriptions.subscription_types import create_type
from domains.people.clients.models import Child, ChildContact, ParentContact
from domains.platform.core.audit import AuditLog
from domains.platform.core.utils import today_for_org
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User

from .models import Payment
from .services import cancel_payment, record_payment


def make_center(slug, phone):
    org = Organization.objects.create(name=slug, slug=slug)
    branch = Branch.objects.create(organization=org, name="Филиал на Абая")
    direction = Direction.objects.create(organization=org, name="Балет")
    child = Child.objects.create(
        organization=org,
        full_name="Иванов Алихан",
        birth_date=date(2018, 1, 1),
        gender=Child.Gender.MALE,
    )
    admin = User.objects.create_user(
        phone=phone, password="pass", full_name="Админ", organization=org, role=User.Role.ADMIN
    )
    subscription_type = create_type(
        org,
        name="8 занятий",
        price=25000,
        quota_sessions=8,
        duration_days=30,
        directions=[direction],
    )
    return org, branch, direction, child, admin, subscription_type


def api(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class SaleDiscountTests(TestCase):
    """Пункт 1: 0 ≤ discount_amount ≤ list_price, иначе ошибка."""

    def setUp(self):
        (
            self.org,
            self.branch,
            self.direction,
            self.child,
            self.admin,
            self.type,
        ) = make_center("true-ballet", "77001112233")

    def sell(self, discount_amount, paid_amount=0):
        return sell_subscription(
            actor=self.admin,
            child=self.child,
            subscription_type_version=self.type.versions.latest(),
            direction=self.direction,
            branch=self.branch,
            starts_on=date.today(),
            discount_amount=discount_amount,
            discount_reason=Subscription.DiscountReason.PROMOTION,
            paid_amount=paid_amount,
            payment_method=Payment.Method.CASH,
        )

    def test_discount_above_price_rejected_and_nothing_saved(self):
        with self.assertRaises(ValueError):
            self.sell(discount_amount=35000)
        self.assertFalse(Subscription.objects.filter(child=self.child).exists())

    def test_negative_discount_rejected(self):
        with self.assertRaises(ValueError):
            self.sell(discount_amount=-1000)

    def test_discount_equal_to_price_gives_zero_price(self):
        subscription, payment = self.sell(discount_amount=25000)
        self.assertEqual(subscription.price, 0)
        self.assertIsNone(payment)

    def test_sell_api_returns_400(self):
        response = api(self.admin).post(
            "/api/v1/subscriptions/sell/",
            {
                "child_id": self.child.id,
                "subscription_type_id": self.type.id,
                "branch_id": self.branch.id,
                "direction_id": self.direction.id,
                "starts_on": date.today().isoformat(),
                "discount_amount": 35000,
                "discount_reason": Subscription.DiscountReason.PROMOTION,
                "paid_amount": 0,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Subscription.objects.filter(child=self.child).exists())


class PaymentFixturesMixin:
    def setUp(self):
        (
            self.org,
            self.branch,
            self.direction,
            self.child,
            self.admin,
            self.type,
        ) = make_center("true-ballet", "77001112233")
        self.subscription, self.payment = sell_subscription(
            actor=self.admin,
            child=self.child,
            subscription_type_version=self.type.versions.latest(),
            direction=self.direction,
            branch=self.branch,
            starts_on=date.today(),
            paid_amount=25000,
            payment_method=Payment.Method.KASPI_TRANSFER,
        )
        self.parent = ParentContact.objects.create(
            organization=self.org, full_name="Иванова Айгуль"
        )
        self.link = ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=self.parent,
            role=ChildContact.Role.MOTHER,
        )


class PaymentParentFilterTests(PaymentFixturesMixin, TestCase):
    """Пункт 2: ?parent_id= — id родителя, не связи; мусор — пустой список."""

    def ids(self, **params):
        response = api(self.admin).get("/api/v1/payments/", params)
        self.assertEqual(response.status_code, 200)
        return [row["id"] for row in response.data["results"]]

    def test_filter_by_parent_id(self):
        self.assertEqual(self.ids(parent_id=self.parent.id), [str(self.payment.id)])

    def test_link_id_is_not_parent_id(self):
        self.assertEqual(self.ids(parent_id=self.link.id), [])

    def test_detached_parent_sees_nothing(self):
        self.link.delete()  # мягкое удаление связи — отвязка
        self.assertEqual(self.ids(parent_id=self.parent.id), [])

    def test_garbage_uuid_gives_empty_list(self):
        for param in ("parent_id", "child_id", "subscription_id"):
            with self.subTest(param=param):
                self.assertEqual(self.ids(**{param: "not-a-uuid"}), [])


@tag("tenant_isolation")
class PaymentParentFilterIsolationTests(PaymentFixturesMixin, TestCase):
    def test_foreign_parent_id_gives_nothing(self):
        _, _, _, _, foreign_admin, _ = make_center("other", "77009998877")
        response = api(foreign_admin).get("/api/v1/payments/", {"parent_id": self.parent.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"], [])


class PaymentDoubleCancelTests(PaymentFixturesMixin, TestCase):
    """Пункт 3: повторная отмена — 400, причина и аудит не меняются."""

    def cancel(self, reason):
        return api(self.admin).post(
            f"/api/v1/payments/{self.payment.id}/cancel/", {"reason": reason}, format="json"
        )

    def test_second_cancel_rejected(self):
        self.assertEqual(self.cancel("Ошибка ввода").status_code, 200)

        response = self.cancel("Дубль")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["detail"], "Оплата уже отменена")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.cancelled_reason, "Ошибка ввода")
        deletes = AuditLog.objects.filter(object_id=self.payment.pk, action=AuditLog.Action.DELETE)
        self.assertEqual(deletes.count(), 1)

    def test_service_rejects_stale_instance(self):
        # Второй запрос держит экземпляр, прочитанный до первой отмены.
        stale = Payment.objects.get(pk=self.payment.pk)
        cancel_payment(self.payment, actor=self.admin, reason="Ошибка ввода")
        with self.assertRaisesMessage(ValueError, "Оплата уже отменена"):
            cancel_payment(stale, actor=self.admin, reason="Дубль")


class PaymentDateTests(PaymentFixturesMixin, TestCase):
    """Пункт 4: дата оплаты — по умолчанию сегодня, не в будущем."""

    def post(self, **extra):
        payload = {
            "subscription": self.subscription.id,
            "amount": 5000,
            "method": Payment.Method.KASPI_TRANSFER,
            **extra,
        }
        return api(self.admin).post("/api/v1/payments/", payload, format="json")

    def local_date(self, payment):
        tz = pytz.timezone(self.org.timezone)
        return payment.paid_at.astimezone(tz).date()

    def test_default_is_today(self):
        response = self.post()
        self.assertEqual(response.status_code, 201)
        payment = Payment.objects.get(pk=response.data["id"])
        self.assertEqual(self.local_date(payment), today_for_org(self.org))

    def test_yesterday_transfer_recorded_yesterday(self):
        yesterday = today_for_org(self.org) - timedelta(days=1)
        response = self.post(paid_on=yesterday.isoformat())
        self.assertEqual(response.status_code, 201)
        payment = Payment.objects.get(pk=response.data["id"])
        self.assertEqual(self.local_date(payment), yesterday)
        # Дата не съезжает и в UTC — полдень по поясу центра.
        self.assertEqual(payment.paid_at.astimezone(pytz.UTC).date(), yesterday)

    def test_future_date_rejected(self):
        tomorrow = today_for_org(self.org) + timedelta(days=1)
        response = self.post(paid_on=tomorrow.isoformat())
        self.assertEqual(response.status_code, 400)
        self.assertIn("paid_on", response.data)
        self.assertEqual(Payment.objects.filter(subscription=self.subscription).count(), 1)

    def test_service_rejects_future_date(self):
        tomorrow = today_for_org(self.org) + timedelta(days=1)
        with self.assertRaises(ValueError):
            record_payment(
                actor=self.admin,
                subscription=self.subscription,
                amount=5000,
                method=Payment.Method.CASH,
                paid_on=tomorrow,
            )

    def test_backdated_payment_counts_in_that_day_revenue(self):
        yesterday = today_for_org(self.org) - timedelta(days=1)
        record_payment(
            actor=self.admin,
            subscription=self.subscription,
            amount=5000,
            method=Payment.Method.CASH,
            paid_on=yesterday,
        )
        tz = pytz.timezone(self.org.timezone)
        start = tz.localize(datetime.combine(yesterday, datetime.min.time()))
        day_total = Payment.objects.filter(
            subscription=self.subscription,
            paid_at__gte=start,
            paid_at__lt=start + timedelta(days=1),
        )
        self.assertEqual([p.amount for p in day_total], [5000])
