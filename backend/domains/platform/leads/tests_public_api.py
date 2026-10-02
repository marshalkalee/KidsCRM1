from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from domains.platform.tenants.models import Branch, Direction, Organization

from .models import Lead, LeadComment


class PublicLeadApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(
            name="True Ballet", slug="true-ballet", website_domain="https://trueballet.kz"
        )
        self.branch = Branch.objects.create(organization=self.org, name="Филиал на Абая")
        self.ballet = Direction.objects.create(organization=self.org, name="Балет")
        self.client = APIClient()

    def url(self, key=None):
        return f"/api/v1/public/leads/{key or self.org.public_api_key}/"

    def test_valid_submission_creates_lead_with_site_source(self):
        response = self.client.post(
            self.url(),
            {
                "parent_name": "Гульнара",
                "phone": "87071234567",
                "child_name": "Алихан",
                "child_age": 5,
                "direction_id": str(self.ballet.id),
                "branch_id": str(self.branch.id),
                "comment": "Удобно по вечерам",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data, {"status": "accepted"})
        lead = Lead.objects.get(organization=self.org)
        self.assertEqual(lead.phone, "+77071234567")
        self.assertEqual(lead.status, Lead.Status.NEW)
        self.assertEqual(lead.source.name, "Сайт")
        self.assertEqual(lead.branch, self.branch)
        self.assertEqual(lead.direction, self.ballet)
        self.assertEqual(LeadComment.objects.get(lead=lead).text, "Удобно по вечерам")

    def test_invalid_phone_rejected_with_400(self):
        response = self.client.post(
            self.url(), {"parent_name": "Гульнара", "phone": "не телефон"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Lead.objects.count(), 0)

    def test_honeypot_filled_returns_generic_success_and_creates_nothing(self):
        response = self.client.post(
            self.url(),
            {"parent_name": "Бот", "phone": "87071234567", "website": "http://spam.example"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data, {"status": "accepted"})
        self.assertEqual(Lead.objects.count(), 0)

    def test_duplicate_within_window_not_created_twice(self):
        payload = {"parent_name": "Гульнара", "phone": "87071234567"}
        first = self.client.post(self.url(), payload, format="json")
        second = self.client.post(self.url(), payload, format="json")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.data, second.data)
        self.assertEqual(Lead.objects.count(), 1)

    def test_duplicate_after_window_creates_second_lead(self):
        self.client.post(
            self.url(), {"parent_name": "Гульнара", "phone": "87071234567"}, format="json"
        )
        Lead.objects.update(created_at=timezone.now() - timedelta(minutes=15))
        self.client.post(
            self.url(), {"parent_name": "Гульнара", "phone": "87071234567"}, format="json"
        )
        self.assertEqual(Lead.objects.count(), 2)

    def test_unknown_key_returns_generic_success_without_leaking(self):
        response = self.client.post(
            self.url(key="not-a-real-key"),
            {"parent_name": "X", "phone": "87071234567"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data, {"status": "accepted"})
        self.assertEqual(Lead.objects.count(), 0)

    def test_branch_from_another_organization_is_ignored(self):
        other_org = Organization.objects.create(name="Другой центр", slug="other")
        foreign_branch = Branch.objects.create(organization=other_org, name="Чужой филиал")
        self.client.post(
            self.url(),
            {
                "parent_name": "Гульнара",
                "phone": "87071234567",
                "branch_id": str(foreign_branch.id),
            },
            format="json",
        )
        lead = Lead.objects.get(organization=self.org)
        self.assertIsNone(lead.branch)

    def test_cors_header_only_for_matching_origin(self):
        matching = self.client.post(
            self.url(),
            {"parent_name": "Гульнара", "phone": "87071234567"},
            format="json",
            HTTP_ORIGIN="https://trueballet.kz",
        )
        self.assertEqual(matching["Access-Control-Allow-Origin"], "https://trueballet.kz")

        other = self.client.post(
            self.url(),
            {"parent_name": "Гульнара", "phone": "87071234568"},
            format="json",
            HTTP_ORIGIN="https://evil.example",
        )
        self.assertNotIn("Access-Control-Allow-Origin", other)

    def test_rate_limit_by_ip(self):
        for i in range(10):
            self.client.post(
                self.url(),
                {"parent_name": "Гульнара", "phone": f"8707123456{i % 9}"},
                format="json",
            )
        blocked = self.client.post(
            self.url(), {"parent_name": "Гульнара", "phone": "87071234569"}, format="json"
        )
        self.assertEqual(blocked.status_code, 429)
