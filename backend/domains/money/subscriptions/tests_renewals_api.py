from datetime import timedelta

from rest_framework.test import APITestCase

from domains.people.clients.models import Child, ChildContact, ContactPhone, ParentContact
from domains.platform.core.utils import today_for_org
from domains.platform.leads.services import create_renewal_lead
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User

from .models import Subscription, SubscriptionLedgerEntry
from .renewals import expiring_child_ids
from .subscription_types import create_type
from .subscriptions import add_ledger_entry


class RenewalsApiTests(APITestCase):
    """TRU-69: экран «Продления» во frontend2 — тот же список, что фильтр
    «заканчивается» у детей; «связались»; продление продаётся из экрана."""

    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.branch = Branch.objects.create(organization=self.org, name="Абая")
        self.ballet = Direction.objects.create(organization=self.org, name="Балет")
        # Филиалы у типа не указаны — продаётся во всех.
        self.type = create_type(
            self.org,
            name="8 занятий",
            price=30000,
            quota_sessions=8,
            duration_days=30,
            directions=[self.ballet],
        )
        self.admin = User.objects.create_user(
            phone="+77010000001",
            password="x",
            full_name="Айнур",
            organization=self.org,
            role=User.Role.ADMIN,
        )
        self.today = today_for_org(self.org)
        self.soon = self.sub("Скоро Конец", ends_in=2, left=6)
        self.few = self.sub("Мало Занятий", ends_in=25, left=1)
        self.sub("Всё Хорошо", ends_in=25, left=6)
        parent = ParentContact.objects.create(organization=self.org, full_name="Мама")
        ContactPhone.objects.create(
            organization=self.org, parent_contact=parent, number="+77071112233"
        )
        ChildContact.objects.create(
            organization=self.org, child=self.soon.child, parent_contact=parent, is_payer=True
        )
        self.client.force_authenticate(self.admin)

    def sub(self, name, *, ends_in, left):
        child = Child.objects.create(
            organization=self.org, full_name=name, birth_date=self.today - timedelta(days=3000)
        )
        subscription = Subscription.objects.create(
            organization=self.org,
            child=child,
            subscription_type_version=self.type.versions.latest(),
            direction=self.ballet,
            branch=self.branch,
            starts_on=self.today - timedelta(days=30 - ends_in),
            ends_on=self.today + timedelta(days=ends_in),
            list_price=30000,
            price=30000,
        )
        add_ledger_entry(subscription, kind=SubscriptionLedgerEntry.Kind.INITIAL_GRANT, delta=left)
        return subscription

    def list(self, **params):
        return self.client.get("/api/v1/subscriptions/renewals/", params).data

    def test_same_list_as_children_filter_sorted_by_urgency(self):
        data = self.list()
        self.assertEqual(
            [r["child_name"] for r in data["results"]], ["Скоро Конец", "Мало Занятий"]
        )
        in_filter = {row["child_id"] for row in expiring_child_ids(self.org)}
        self.assertEqual({r["child_id"] for r in data["results"]}, {str(c) for c in in_filter})
        first = data["results"][0]
        self.assertEqual(first["days_left"], 2)
        self.assertEqual(first["parent_name"], "Мама")
        self.assertIn("Продлеваем?", first["message_text"])

    def test_contacted_mark_is_saved_and_filters(self):
        response = self.client.post(
            f"/api/v1/subscriptions/renewals/{self.soon.pk}/contacted/", {"note": "Подумают"}
        )
        self.assertEqual(response.status_code, 201)
        row = self.list(q="Скоро")["results"][0]
        self.assertTrue(row["contacted_recently"])
        self.assertEqual(row["last_contacted_by"], "Айнур")
        self.assertEqual(row["last_contact_note"], "Подумают")
        not_called = self.list(not_contacted="1")
        self.assertEqual([r["child_name"] for r in not_called["results"]], ["Мало Занятий"])

    def test_open_renewal_lead_is_shown(self):
        lead, _ = create_renewal_lead(self.soon.child, actor=self.admin)
        row = self.list(q="Скоро")["results"][0]
        self.assertEqual(row["renewal_lead_id"], str(lead.pk))

    def test_renewal_is_sold_from_the_screen(self):
        row = self.list(q="Скоро")["results"][0]
        response = self.client.post(
            f"/api/v1/subscriptions/{row['subscription_id']}/renew/",
            {
                "subscription_type_id": row["subscription_type_id"],
                "starts_on": row["ends_on"],
                "paid_amount": "30000",
                "payment_method": "kaspi_transfer",
            },
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["renewed_from"], self.soon.pk)
        self.assertEqual(response.data["debt"], "0")
        # Продлённый уходит и из «Продлений», и из фильтра «заканчивается» у детей.
        self.assertEqual([r["child_name"] for r in self.list()["results"]], ["Мало Занятий"])
        in_filter = {row["child_id"] for row in expiring_child_ids(self.org)}
        self.assertNotIn(self.soon.child_id, in_filter)

    def test_renew_with_bad_input_is_400(self):
        response = self.client.post(
            f"/api/v1/subscriptions/{self.soon.pk}/renew/",
            {"subscription_type_id": str(self.type.pk), "starts_on": "завтра"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("starts_on", response.data)

    def test_types_for_branch(self):
        response = self.client.get("/api/v1/subscriptions/types/", {"branch": str(self.branch.pk)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([t["name"] for t in response.data], ["8 занятий"])

    def test_sell_works_with_real_request(self):
        child = Child.objects.create(
            organization=self.org,
            full_name="Новенький",
            birth_date=self.today - timedelta(days=3000),
        )
        response = self.client.post(
            "/api/v1/subscriptions/sell/",
            {
                "child_id": str(child.pk),
                "subscription_type_id": str(self.type.pk),
                "branch_id": str(self.branch.pk),
                "direction_id": str(self.ballet.pk),
                "starts_on": self.today.isoformat(),
                "paid_amount": "10000",
                "payment_method": "cash",
            },
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["debt"], "20000")
        self.assertEqual(response.data["sessions_remaining_cache"], 8)

    def test_teacher_has_no_access(self):
        teacher = User.objects.create_user(
            phone="+77010000009",
            password="x",
            full_name="Педагог",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        self.client.force_authenticate(teacher)
        self.assertEqual(self.client.get("/api/v1/subscriptions/renewals/").status_code, 403)
