import datetime

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from domains.money.payments.models import Payment
from domains.money.subscriptions.models import Subscription, SubscriptionLedgerEntry
from domains.money.subscriptions.subscription_types import create_type
from domains.people.clients.models import Child, ChildContact
from domains.people.clients.services import ChildService
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.schedule.models import Lesson, LessonEnrollment

from .models import Lead, LeadStatusChange
from .services import change_status, create_lead


def authenticated_client(user):
    refresh = RefreshToken.for_user(user)
    refresh["organization_id"] = str(user.organization_id)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


class LeadSaleApiTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="lead-sale")
        self.branch = Branch.objects.create(organization=self.org, name="Филиал 1")
        self.direction = Direction.objects.create(organization=self.org, name="Балет")
        self.owner = User.objects.create_user(
            phone="+77010000700",
            password="pass",
            full_name="Владелец Тестов",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.client = authenticated_client(self.owner)
        self.lead = create_lead(
            organization=self.org,
            actor=self.owner,
            parent_name="Айгерим Серикова",
            phone="+77071112233",
            child_name="Алия Серикова",
            child_age=7,
            branch=self.branch,
            direction=self.direction,
        )
        self.lead = change_status(
            self.lead, to_status=Lead.Status.TRIAL_SCHEDULED, actor=self.owner
        )
        self.lead = change_status(self.lead, to_status=Lead.Status.TRIAL_ATTENDED, actor=self.owner)
        self.child = ChildService.create_with_parent(
            self.org,
            child_data={
                "full_name": "Алия Серикова",
                "birth_date": datetime.date(2019, 4, 12),
                "gender": Child.Gender.FEMALE,
                "consent_given": True,
            },
            parent_data={
                "full_name": "Айгерим Серикова",
                "phones": [self.lead.phone],
            },
            link_role=ChildContact.Role.MOTHER,
        )
        self.child.directions.add(self.direction)
        self.lead.converted_child = self.child
        self.lead.save(update_fields=["converted_child", "updated_at"])
        self.subscription_type = create_type(
            self.org,
            name="8 занятий",
            price=30000,
            quota_sessions=8,
            duration_days=30,
            directions=[self.direction],
            branches=[self.branch],
        )
        self.group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Балет 7–9",
            capacity=12,
            age_min=7,
            age_max=9,
        )

    @property
    def url(self):
        return f"/api/v1/leads/{self.lead.id}/sale/"

    def payload(self, **overrides):
        data = {
            "subscription_type": str(self.subscription_type.id),
            "starts_on": timezone.localdate().isoformat(),
            "discount_amount": "2000",
            "discount_reason": Subscription.DiscountReason.PROMOTION,
            "discount_comment": "Скидка с пробного",
            "paid_amount": "28000",
            "payment_method": Payment.Method.KASPI_TRANSFER,
            "comment": "Оплачено администратору",
            "group": str(self.group.id),
        }
        data.update(overrides)
        return data

    def test_options_are_prefilled_and_only_suitable_entities_are_returned(self):
        other_direction = Direction.objects.create(organization=self.org, name="Рисование")
        hidden_type = create_type(
            self.org,
            name="Не подходит",
            price=10000,
            quota_sessions=4,
            duration_days=30,
            directions=[other_direction],
        )
        Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Балет 12–15",
            capacity=12,
            age_min=12,
            age_max=15,
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["needs_conversion"])
        self.assertEqual(response.data["child"]["id"], str(self.child.id))
        self.assertEqual(response.data["direction"]["id"], str(self.direction.id))
        self.assertEqual(response.data["branch"]["id"], str(self.branch.id))
        self.assertEqual(
            [row["id"] for row in response.data["types"]], [str(self.subscription_type.id)]
        )
        self.assertNotIn(str(hidden_type.id), [row["id"] for row in response.data["types"]])
        self.assertEqual([row["id"] for row in response.data["groups"]], [str(self.group.id)])
        self.assertEqual(response.data["groups"][0]["spots_left"], 12)

    def test_sale_closes_lead_records_money_and_adds_child_to_group(self):
        response = self.client.post(self.url, self.payload(), format="json")

        self.assertEqual(response.status_code, 201, response.data)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, Lead.Status.PURCHASED)
        self.assertIsNotNone(self.lead.sold_subscription_id)
        subscription = Subscription.objects.get(pk=self.lead.sold_subscription_id)
        self.assertEqual(subscription.child, self.child)
        self.assertEqual(subscription.direction, self.direction)
        self.assertEqual(subscription.branch, self.branch)
        self.assertEqual(subscription.list_price, 30000)
        self.assertEqual(subscription.discount_amount, 2000)
        self.assertEqual(subscription.price, 28000)
        self.assertEqual(subscription.sessions_remaining_cache, 8)
        self.assertTrue(
            SubscriptionLedgerEntry.objects.filter(
                subscription=subscription,
                kind=SubscriptionLedgerEntry.Kind.INITIAL_GRANT,
                delta=8,
            ).exists()
        )
        self.assertEqual(subscription.payments.get().amount, 28000)
        membership = GroupMembership.objects.get(group=self.group, child=self.child)
        self.assertEqual(response.data["group_membership_id"], str(membership.id))
        status_change = LeadStatusChange.objects.get(
            lead=self.lead, to_status=Lead.Status.PURCHASED
        )
        self.assertEqual(status_change.from_status, Lead.Status.TRIAL_ATTENDED)
        self.assertIn("8 занятий", status_change.comment)
        self.assertEqual(response.data["sold_subscription_details"]["id"], str(subscription.id))

    def test_sale_is_idempotent(self):
        first = self.client.post(self.url, self.payload(), format="json")
        second = self.client.post(self.url, self.payload(), format="json")

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(Subscription.objects.filter(child=self.child).count(), 1)
        self.assertEqual(GroupMembership.objects.filter(child=self.child).count(), 1)
        self.assertEqual(
            LeadStatusChange.objects.filter(
                lead=self.lead, to_status=Lead.Status.PURCHASED
            ).count(),
            1,
        )

    def test_subscription_can_be_created_after_manual_purchased_status(self):
        self.lead = change_status(self.lead, to_status=Lead.Status.PURCHASED, actor=self.owner)

        response = self.client.post(self.url, self.payload(), format="json")

        self.assertEqual(response.status_code, 201, response.data)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, Lead.Status.PURCHASED)
        self.assertIsNotNone(self.lead.sold_subscription_id)
        self.assertEqual(
            LeadStatusChange.objects.filter(
                lead=self.lead, to_status=Lead.Status.PURCHASED
            ).count(),
            1,
        )

    def test_unsuitable_group_rolls_back_entire_sale(self):
        wrong_group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Взрослая группа",
            capacity=12,
            age_min=15,
            age_max=18,
        )

        response = self.client.post(
            self.url, self.payload(group=str(wrong_group.id)), format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Subscription.objects.count(), 0)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, Lead.Status.TRIAL_ATTENDED)
        self.assertIsNone(self.lead.sold_subscription_id)

    def test_sale_requires_conversion_first(self):
        self.lead.converted_child = None
        self.lead.save(update_fields=["converted_child", "updated_at"])

        preview = self.client.get(self.url)
        response = self.client.post(self.url, self.payload(), format="json")

        self.assertEqual(preview.status_code, 200)
        self.assertTrue(preview.data["needs_conversion"])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Subscription.objects.count(), 0)

    def test_complete_sales_path_stays_in_one_lead(self):
        lead = create_lead(
            organization=self.org,
            actor=self.owner,
            parent_name="Мадина Исаева",
            phone="+77072223344",
            child_name="София Исаева",
            child_age=7,
            branch=self.branch,
            direction=self.direction,
        )
        contacted = self.client.post(
            f"/api/v1/leads/{lead.id}/status/",
            {"status": Lead.Status.CONTACTED},
            format="json",
        )
        starts = timezone.now() + datetime.timedelta(days=2)
        lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            starts_at=starts,
            ends_at=starts + datetime.timedelta(hours=1),
        )
        booked = self.client.post(
            f"/api/v1/leads/{lead.id}/book-trial/",
            {"lesson": str(lesson.id)},
            format="json",
        )
        enrollment = LessonEnrollment.objects.get(source_lead=lead)
        attended = self.client.post(
            "/api/v1/attendance/mark/",
            {
                "lesson": str(lesson.id),
                "child": str(enrollment.child_id),
                "status": "present",
            },
            format="json",
        )
        converted = self.client.post(
            f"/api/v1/leads/{lead.id}/conversion/",
            {
                "decision": "create_new",
                "child_name": "София Исаева",
                "birth_date": "2019-05-10",
                "gender": "female",
                "parent_name": "Мадина Исаева",
                "link_role": "mother",
                "consent_given": True,
            },
            format="json",
        )
        sold = self.client.post(
            f"/api/v1/leads/{lead.id}/sale/",
            self.payload(discount_amount="0", discount_reason="", paid_amount="30000"),
            format="json",
        )

        self.assertEqual(contacted.status_code, 200, contacted.data)
        self.assertEqual(booked.status_code, 201, booked.data)
        self.assertEqual(attended.status_code, 200, attended.data)
        self.assertEqual(converted.status_code, 201, converted.data)
        self.assertEqual(sold.status_code, 201, sold.data)
        lead.refresh_from_db()
        self.assertEqual(lead.status, Lead.Status.PURCHASED)
        self.assertIsNotNone(lead.converted_child_id)
        self.assertIsNotNone(lead.sold_subscription_id)
        self.assertTrue(
            GroupMembership.objects.filter(
                group=self.group, child_id=lead.converted_child_id, left_at__isnull=True
            ).exists()
        )
        self.assertEqual(
            list(lead.status_changes.values_list("to_status", flat=True)),
            [
                Lead.Status.NEW,
                Lead.Status.CONTACTED,
                Lead.Status.TRIAL_SCHEDULED,
                Lead.Status.TRIAL_ATTENDED,
                Lead.Status.PURCHASED,
            ],
        )

    def test_direct_buyer_is_converted_before_sale_without_trial(self):
        lead = create_lead(
            organization=self.org,
            actor=self.owner,
            parent_name="Лаура Ким",
            phone="+77073334455",
            child_name="Мира Ким",
            child_age=7,
            branch=self.branch,
            direction=self.direction,
        )
        lead = change_status(lead, to_status=Lead.Status.CONTACTED, actor=self.owner)

        converted = self.client.post(
            f"/api/v1/leads/{lead.id}/conversion/",
            {
                "decision": "create_new",
                "child_name": "Мира Ким",
                "birth_date": "2019-06-15",
                "gender": "female",
                "parent_name": "Лаура Ким",
                "link_role": "mother",
                "consent_given": True,
            },
            format="json",
        )
        sold = self.client.post(
            f"/api/v1/leads/{lead.id}/sale/",
            self.payload(discount_amount="0", discount_reason="", paid_amount="30000"),
            format="json",
        )

        self.assertEqual(converted.status_code, 201, converted.data)
        self.assertEqual(sold.status_code, 201, sold.data)
        lead.refresh_from_db()
        self.assertEqual(lead.status, Lead.Status.PURCHASED)
        self.assertIsNotNone(lead.converted_child_id)
        self.assertEqual(lead.sold_subscription.child_id, lead.converted_child_id)
