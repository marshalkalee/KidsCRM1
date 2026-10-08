"""
Критичные исправления после ревью денежного домена:
- оплата на абонемент чужой организации (изоляция тенантов);
- сумма оплаты ≤ 0;
- веб-экран быстрой оплаты без проверки прав;
- ночная задача статусов падала на закончившейся заморозке.
"""

from datetime import date, timedelta

from django.test import TestCase, tag
from rest_framework.test import APIClient

from domains.money.subscriptions.freezes import freeze_subscription
from domains.money.subscriptions.models import Subscription
from domains.money.subscriptions.statuses import update_all_subscription_statuses
from domains.money.subscriptions.subscription_types import create_type
from domains.people.clients.models import Child
from domains.platform.core.audit import AuditLog
from domains.platform.tenants.models import Direction, Organization
from domains.platform.users.models import User

from .models import Payment
from .services import record_payment


def make_org(slug, phone_prefix):
    org = Organization.objects.create(name=slug, slug=slug)
    direction = Direction.objects.create(organization=org, name="Балет")
    child = Child.objects.create(
        organization=org,
        full_name="Иванов Алихан",
        birth_date=date(2018, 1, 1),
        gender=Child.Gender.MALE,
    )
    users = {
        role: User.objects.create_user(
            phone=f"{phone_prefix}{index}",
            password="pass",
            full_name=role,
            organization=org,
            role=role,
        )
        for index, role in enumerate(
            [User.Role.OWNER, User.Role.ADMIN, User.Role.TEACHER, User.Role.ACCOUNTANT]
        )
    }
    st = create_type(
        org,
        name="8 занятий",
        price=25000,
        quota_sessions=8,
        duration_days=30,
        directions=[direction],
    )
    sub = Subscription.objects.create(
        organization=org,
        child=child,
        subscription_type_version=st.versions.latest(),
        direction=direction,
        starts_on=date.today(),
        ends_on=date.today() + timedelta(days=30),
        list_price=25000,
        price=25000,
        sessions_remaining_cache=8,
    )
    return org, child, users, sub


def api(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@tag("tenant_isolation")
class PaymentTenantIsolationTests(TestCase):
    def setUp(self):
        self.org_a, _, self.users_a, self.sub_a = make_org("a", "7701000000")
        self.org_b, _, self.users_b, self.sub_b = make_org("b", "7702000000")

    def test_cannot_pay_foreign_subscription(self):
        response = api(self.users_b[User.Role.OWNER]).post(
            "/api/v1/payments/",
            {"subscription": str(self.sub_a.id), "amount": "1000", "method": "cash"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("subscription", response.data)
        self.assertFalse(Payment.objects.filter(subscription=self.sub_a).exists())

    def test_own_subscription_still_works(self):
        response = api(self.users_a[User.Role.ADMIN]).post(
            "/api/v1/payments/",
            {"subscription": str(self.sub_a.id), "amount": "1000", "method": "cash"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)


class PaymentAmountTests(TestCase):
    def setUp(self):
        self.org, _, self.users, self.sub = make_org("a", "7701000000")

    def test_api_rejects_zero_and_negative(self):
        for amount in ("0", "-50000"):
            response = api(self.users[User.Role.ADMIN]).post(
                "/api/v1/payments/",
                {"subscription": str(self.sub.id), "amount": amount, "method": "cash"},
                format="json",
            )
            self.assertEqual(response.status_code, 400, amount)
            self.assertIn("amount", response.data)
        self.assertFalse(Payment.objects.exists())

    def test_service_rejects_non_positive(self):
        with self.assertRaises(ValueError):
            record_payment(
                actor=self.users[User.Role.ADMIN], subscription=self.sub, amount=-1, method="cash"
            )


class QuickPaymentApiPermissionTests(TestCase):
    """Права на приём оплаты — на API, которым пользуется frontend2
    (раньше то же проверялось на серверной странице, удалённой в TRU-88)."""

    def setUp(self):
        self.org, self.child, self.users, self.sub = make_org("a", "7701000000")
        self.url = "/api/v1/payments/"

    def client_for(self, user=None):
        client = APIClient()
        if user is not None:
            client.force_authenticate(user)
        return client

    def post_payment(self, user, amount="700", key="11111111-1111-1111-1111-111111111111"):
        return self.client_for(user).post(
            self.url,
            {
                "subscription": str(self.sub.id),
                "amount": amount,
                "method": "cash",
                "idempotency_key": key,
            },
            format="json",
        )

    def test_anonymous_gets_401(self):
        self.assertEqual(self.client_for().get(self.url).status_code, 401)
        self.assertEqual(self.client_for().post(self.url, {}, format="json").status_code, 401)

    def test_teacher_cannot_record_or_see(self):
        teacher = self.users[User.Role.TEACHER]
        self.assertEqual(self.post_payment(teacher).status_code, 403)
        self.assertEqual(self.client_for(teacher).get(self.url).status_code, 403)
        self.assertFalse(Payment.objects.exists())

    def test_accountant_sees_but_cannot_record(self):
        accountant = self.users[User.Role.ACCOUNTANT]
        self.assertEqual(self.client_for(accountant).get(self.url).status_code, 200)
        self.assertEqual(self.post_payment(accountant).status_code, 403)
        self.assertFalse(Payment.objects.exists())

    def test_admin_records(self):
        self.assertEqual(self.post_payment(self.users[User.Role.ADMIN]).status_code, 201)
        self.assertEqual(Payment.objects.count(), 1)

    def test_negative_and_garbage_amount_rejected(self):
        admin = self.users[User.Role.ADMIN]
        self.assertEqual(self.post_payment(admin, amount="-500").status_code, 400)
        self.assertEqual(self.post_payment(admin, amount="abc", key=None).status_code, 400)
        self.assertFalse(Payment.objects.exists())


class NightlyStatusFreezeTests(TestCase):
    def setUp(self):
        self.org, self.child, self.users, self.sub = make_org("a", "7701000000")

    def test_finished_freeze_unfreezes_without_crash(self):
        freeze_subscription(
            self.sub,
            actor=self.users[User.Role.ADMIN],
            starts_on=date.today() - timedelta(days=10),
            ends_on=date.today() + timedelta(days=2),
        )
        # Заморозка закончилась вчера (сдвигаем её даты прямо в базе): ночная
        # задача ещё не успела разморозить абонемент.
        self.sub.freezes.update(ends_on=date.today() - timedelta(days=2))
        self.sub.refresh_from_db()
        ends_on = self.sub.ends_on
        self.assertEqual(self.sub.status, Subscription.Status.FROZEN)

        update_all_subscription_statuses()

        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.ACTIVE)
        # Срок уже сдвинут при заморозке — второй раз не сдвигаем.
        self.assertEqual(self.sub.ends_on, ends_on)
        self.assertTrue(
            AuditLog.objects.filter(
                object_id=self.sub.id, action=AuditLog.Action.UNFREEZE, actor=None
            ).exists()
        )

    def test_ongoing_freeze_stays_frozen(self):
        freeze_subscription(
            self.sub,
            actor=self.users[User.Role.ADMIN],
            starts_on=date.today() - timedelta(days=2),
            ends_on=date.today() + timedelta(days=5),
        )
        update_all_subscription_statuses()
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Subscription.Status.FROZEN)

    def test_one_broken_subscription_does_not_stop_others(self):
        broken = self.sub
        _, _, _, other = make_org("b", "7702000000")
        Subscription.objects.filter(pk=other.pk).update(ends_on=date.today() - timedelta(days=1))
        # «Сломанный»: статус, из которого переход в EXPIRED недопустим, но
        # фильтр ночной задачи его всё равно выбирает — имитация сбоя строки.
        Subscription.objects.filter(pk=broken.pk).update(
            ends_on=date.today() - timedelta(days=1), status=Subscription.Status.FROZEN
        )
        from unittest import mock

        from domains.money.subscriptions import statuses

        real = statuses.transition_status

        def flaky(subscription, new_status):
            if subscription.pk == broken.pk:
                raise RuntimeError("сбой")
            return real(subscription, new_status)

        with mock.patch.object(statuses, "transition_status", side_effect=flaky):
            update_all_subscription_statuses()
        other.refresh_from_db()
        self.assertEqual(other.status, Subscription.Status.EXPIRED)
