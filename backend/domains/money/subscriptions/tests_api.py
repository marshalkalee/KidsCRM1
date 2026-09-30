from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from domains.people.clients.models import Child
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User

from .models import Subscription
from .subscription_types import create_type
from .subscriptions import add_ledger_entry


class SubscriptionApiPermissionTests(TestCase):
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
        add_ledger_entry(self.sub, kind="initial_grant", delta=8)

    def test_teacher_cannot_list_subscriptions(self):
        client = APIClient()
        client.force_authenticate(user=self.teacher)
        response = client.get("/api/v1/subscriptions/", {"child_id": self.child.id})
        self.assertEqual(response.status_code, 403)

    def test_admin_sees_ledger(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        response = client.get(f"/api/v1/subscriptions/{self.sub.id}/ledger/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

    def test_teacher_cannot_see_child_debt(self):
        client = APIClient()
        client.force_authenticate(user=self.teacher)
        response = client.get("/api/v1/payments/child_debt/", {"child_id": self.child.id})
        self.assertEqual(response.status_code, 403)

    def test_admin_sees_child_debt(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        response = client.get("/api/v1/payments/child_debt/", {"child_id": self.child.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["debt"], "30000")
