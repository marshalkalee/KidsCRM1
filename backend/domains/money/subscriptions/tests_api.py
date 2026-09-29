import datetime
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from domains.money.payments.models import Payment
from domains.people.clients.models import Child
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User

from .sales import sell_subscription
from .subscription_types import create_type


class SubscriptionApiTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Балет", slug="subscription-api")
        self.branch = Branch.objects.create(organization=self.org, name="Центр")
        self.direction = Direction.objects.create(organization=self.org, name="Балет")
        self.owner = User.objects.create_user(
            phone="+77010000800",
            password="pass",
            full_name="Владелец",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.teacher = User.objects.create_user(
            phone="+77010000801",
            password="pass",
            full_name="Преподаватель",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        self.child = Child.objects.create(
            organization=self.org,
            full_name="Алия Серикова",
            birth_date=datetime.date(2019, 4, 12),
            gender=Child.Gender.FEMALE,
        )
        self.type = create_type(
            self.org,
            name="8 занятий",
            price=30000,
            quota_sessions=8,
            duration_days=30,
            directions=[self.direction],
            branches=[self.branch],
        )
        self.subscription, _ = sell_subscription(
            actor=self.owner,
            child=self.child,
            subscription_type_version=self.type.versions.latest(),
            direction=self.direction,
            branch=self.branch,
            starts_on=datetime.date.today(),
            ends_on=datetime.date.today() + datetime.timedelta(days=30),
            discount_amount=Decimal("2000"),
            discount_reason="promotion",
            paid_amount=Decimal("20000"),
            payment_method=Payment.Method.CASH,
        )
        self.client = APIClient()

    def test_child_subscription_history_contains_balance_and_context(self):
        self.client.force_authenticate(self.owner)

        response = self.client.get("/api/v1/subscriptions/", {"child_id": str(self.child.id)})

        self.assertEqual(response.status_code, 200, response.data)
        row = response.data["results"][0]
        self.assertEqual(row["id"], str(self.subscription.id))
        self.assertEqual(row["name"], "8 занятий")
        self.assertEqual(row["direction_name"], "Балет")
        self.assertEqual(row["branch_name"], "Центр")
        self.assertEqual(Decimal(row["price"]), Decimal("28000"))
        self.assertEqual(Decimal(row["paid"]), Decimal("20000"))
        self.assertEqual(Decimal(row["debt"]), Decimal("8000"))
        self.assertEqual(row["sessions_remaining_cache"], 8)

    def test_other_organization_cannot_read_subscription(self):
        other = Organization.objects.create(name="Другая", slug="subscription-api-other")
        other_owner = User.objects.create_user(
            phone="+77010000802",
            password="pass",
            full_name="Другой",
            organization=other,
            role=User.Role.OWNER,
        )
        self.client.force_authenticate(other_owner)

        response = self.client.get(f"/api/v1/subscriptions/{self.subscription.id}/")

        self.assertEqual(response.status_code, 404)

    def test_teacher_cannot_view_money(self):
        self.client.force_authenticate(self.teacher)

        response = self.client.get("/api/v1/subscriptions/", {"child_id": str(self.child.id)})

        self.assertEqual(response.status_code, 403)
