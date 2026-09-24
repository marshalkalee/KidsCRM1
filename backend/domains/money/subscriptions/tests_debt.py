"""
debtor_child_ids() — единая точка правды "есть задолженность" для фильтра
списка детей (people/clients) и будущего экрана «Задолженности».
"""

from datetime import date

from django.test import TestCase

from domains.people.clients.models import Child
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User

from .debt import debtor_child_ids
from .sales import sell_subscription
from .subscription_types import create_type


class DebtorChildIdsTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.ballet = Direction.objects.create(organization=self.org, name="Балет")
        self.admin = User.objects.create_user(
            phone="+77001112233",
            password="pass12345",
            full_name="Админ",
            organization=self.org,
            role=User.Role.ADMIN,
        )
        self.subscription_type = create_type(
            self.org, name="8 занятий", price=25000, quota_sessions=8, duration_days=30
        )

    def _make_child(self, name):
        return Child.objects.create(
            organization=self.org,
            full_name=name,
            birth_date=date(2018, 1, 1),
            gender=Child.Gender.MALE,
        )

    def _sell(self, child, paid_amount):
        return sell_subscription(
            actor=self.admin,
            child=child,
            subscription_type_version=self.subscription_type.versions.latest(),
            direction=self.ballet,
            branch=Branch.objects.get_or_create(
                organization=child.organization, name="Центральный"
            )[0],
            starts_on=date.today(),
            ends_on=date.today().replace(day=28),
            paid_amount=paid_amount,
            payment_method="cash",
        )

    def test_underpaid_subscription_counts_as_debtor(self):
        child = self._make_child("Недоплатил")
        self._sell(child, paid_amount=10000)

        self.assertIn(child.id, set(debtor_child_ids(self.org).values_list("child_id", flat=True)))

    def test_fully_paid_subscription_is_not_a_debtor(self):
        child = self._make_child("Оплатил")
        self._sell(child, paid_amount=25000)

        self.assertNotIn(
            child.id, set(debtor_child_ids(self.org).values_list("child_id", flat=True))
        )

    def test_child_without_subscription_is_not_a_debtor(self):
        child = self._make_child("Без абонемента")

        self.assertNotIn(
            child.id, set(debtor_child_ids(self.org).values_list("child_id", flat=True))
        )

    def test_overpaid_subscription_is_not_a_debtor(self):
        child = self._make_child("Переплатил")
        self._sell(child, paid_amount=30000)

        self.assertNotIn(
            child.id, set(debtor_child_ids(self.org).values_list("child_id", flat=True))
        )

    def test_tenant_isolation(self):
        other_org = Organization.objects.create(name="Other", slug="other")
        other_ballet = Direction.objects.create(organization=other_org, name="Балет")
        other_admin = User.objects.create_user(
            phone="+77001112244",
            password="pass12345",
            full_name="Админ 2",
            organization=other_org,
            role=User.Role.ADMIN,
        )
        other_type = create_type(
            other_org, name="8 занятий", price=25000, quota_sessions=8, duration_days=30
        )
        other_child = Child.objects.create(
            organization=other_org,
            full_name="Чужой",
            birth_date=date(2018, 1, 1),
            gender=Child.Gender.MALE,
        )
        sell_subscription(
            actor=other_admin,
            child=other_child,
            subscription_type_version=other_type.versions.latest(),
            direction=other_ballet,
            branch=Branch.objects.get_or_create(
                organization=other_child.organization, name="Центральный"
            )[0],
            starts_on=date.today(),
            ends_on=date.today().replace(day=28),
            paid_amount=0,
            payment_method="cash",
        )

        self.assertNotIn(
            other_child.id, set(debtor_child_ids(self.org).values_list("child_id", flat=True))
        )
