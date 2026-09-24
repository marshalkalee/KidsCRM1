from datetime import date, timedelta

from django.test import TestCase

from domains.money.subscriptions.models import Subscription
from domains.money.subscriptions.subscription_types import create_type
from domains.people.clients.models import Child, ChildContact, ParentContact
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User

from .debt import debt_for_child, debt_for_children, debt_for_parent, debt_for_subscription
from .models import Payment
from .services import cancel_payment, record_payment


class DebtTests(TestCase):
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
            price=30000,
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
            list_price=30000,
            price=30000,
        )

    def test_three_partial_payments_reduce_debt(self):
        self.assertEqual(debt_for_subscription(self.sub), 30000)
        record_payment(
            actor=self.admin, subscription=self.sub, amount=10000, method=Payment.Method.CASH
        )
        record_payment(
            actor=self.admin, subscription=self.sub, amount=10000, method=Payment.Method.CASH
        )
        record_payment(
            actor=self.admin, subscription=self.sub, amount=5000, method=Payment.Method.CASH
        )
        self.assertEqual(debt_for_subscription(self.sub), 5000)

    def test_discounted_price_used_not_list_price(self):
        self.sub.discount_amount = 5000
        self.sub.discount_reason = Subscription.DiscountReason.PROMOTION
        self.sub.price = 25000
        self.sub.save()
        self.assertEqual(debt_for_subscription(self.sub), 25000)

    def test_cancelled_payment_does_not_reduce_debt(self):
        payment = record_payment(
            actor=self.admin, subscription=self.sub, amount=30000, method=Payment.Method.CASH
        )
        cancel_payment(payment, actor=self.admin, reason="Ошибка")
        self.assertEqual(debt_for_subscription(self.sub), 30000)

    def test_debt_for_child_sums_across_subscriptions(self):
        st2 = create_type(
            self.org,
            name="4 занятия",
            price=15000,
            quota_sessions=4,
            duration_days=30,
            directions=[self.ballet],
        )
        Subscription.objects.create(
            organization=self.org,
            child=self.child,
            subscription_type_version=st2.versions.latest(),
            direction=self.ballet,
            branch=self.branch,
            starts_on=date.today(),
            ends_on=date.today() + timedelta(days=30),
            list_price=15000,
            price=15000,
        )
        self.assertEqual(debt_for_child(self.child), 45000)

    def test_debt_for_parent_sums_children_where_payer(self):
        parent = ParentContact.objects.create(organization=self.org, full_name="Иванова Гульнара")
        ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=parent,
            role=ChildContact.Role.MOTHER,
            is_payer=True,
        )
        self.assertEqual(debt_for_parent(parent), debt_for_child(self.child))

    def test_debt_for_children_matches_sum_of_individual(self):
        child2 = Child.objects.create(
            organization=self.org,
            full_name="Петрова Айым",
            birth_date=date(2019, 1, 1),
            gender=Child.Gender.FEMALE,
        )
        st2 = create_type(
            self.org,
            name="8 занятий v2",
            price=28000,
            quota_sessions=8,
            duration_days=30,
            directions=[self.ballet],
        )
        Subscription.objects.create(
            organization=self.org,
            child=child2,
            subscription_type_version=st2.versions.latest(),
            direction=self.ballet,
            branch=self.branch,
            starts_on=date.today(),
            ends_on=date.today() + timedelta(days=30),
            list_price=28000,
            price=28000,
        )
        combined = debt_for_children([self.child, child2])
        self.assertEqual(combined, debt_for_child(self.child) + debt_for_child(child2))
