from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from domains.people.clients.models import Child
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User

from .models import Subscription, SubscriptionType
from .subscription_types import create_type, get_selectable_subscription_types


class SubscriptionTypeApiTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.ballet = Direction.objects.create(organization=self.org, name="Балет")
        self.branch = Branch.objects.create(organization=self.org, name="Филиал на Абая")
        self.owner = User.objects.create_user(
            phone="77001112233",
            password="pass",
            full_name="Владелец",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.teacher = User.objects.create_user(
            phone="77004445566",
            password="pass",
            full_name="Препод",
            organization=self.org,
            role=User.Role.TEACHER,
        )

    def test_owner_creates_type_without_developer(self):
        client = APIClient()
        client.force_authenticate(self.owner)
        response = client.post(
            "/api/v1/subscriptions/subscription-types/",
            {
                "name": "8 занятий",
                "price": 25000,
                "duration_days": 30,
                "is_unlimited": False,
                "quota_sessions": 8,
                "directions": [self.ballet.id],
                "branches": [],
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        created = SubscriptionType.objects.get(name="8 занятий")
        self.assertEqual(created.price, 25000)

    def test_teacher_cannot_create_type(self):
        client = APIClient()
        client.force_authenticate(self.teacher)
        response = client.post(
            "/api/v1/subscriptions/subscription-types/",
            {
                "name": "X",
                "price": 1000,
                "duration_days": 30,
                "quota_sessions": 1,
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_archived_type_not_offered_for_sale(self):
        st = create_type(
            self.org,
            name="Устаревший",
            price=10000,
            quota_sessions=4,
            duration_days=30,
            directions=[self.ballet],
        )
        client = APIClient()
        client.force_authenticate(self.owner)
        client.patch(
            f"/api/v1/subscriptions/subscription-types/{st.id}/",
            {"is_active": False},
            format="json",
        )
        st.refresh_from_db()
        self.assertFalse(st.is_active)
        self.assertNotIn(st, get_selectable_subscription_types(self.org))

    def test_edit_does_not_change_already_sold_price(self):
        st = create_type(
            self.org,
            name="8 занятий",
            price=25000,
            quota_sessions=8,
            duration_days=30,
            directions=[self.ballet],
        )
        child = Child.objects.create(
            organization=self.org,
            full_name="Иванов Алихан",
            birth_date=date(2018, 1, 1),
            gender=Child.Gender.MALE,
        )
        sub = Subscription.objects.create(
            organization=self.org,
            child=child,
            subscription_type_version=st.versions.latest(),
            direction=self.ballet,
            branch=self.branch,
            starts_on=date.today(),
            ends_on=date.today() + timedelta(days=30),
            list_price=25000,
            price=25000,
        )
        client = APIClient()
        client.force_authenticate(self.owner)
        client.patch(
            f"/api/v1/subscriptions/subscription-types/{st.id}/", {"price": 30000}, format="json"
        )
        sub.refresh_from_db()
        self.assertEqual(sub.subscription_type_version.price, 25000)
