"""
API мастера онбординга (TRU-86): шаги по данным, пропуск и возобновление,
завершение; регистрация без slug — slug генерирует сервер.
"""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .models import Branch, Organization

User = get_user_model()
STATE_URL = reverse("tenants:onboarding")


class OnboardingApiTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Новый центр", slug="new-center")
        self.owner = User.objects.create_user(
            phone="+77010000001",
            full_name="Owner",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def test_fresh_organization_starts_at_organization_step(self):
        data = self.api.get(STATE_URL).json()

        self.assertEqual(data["current"], "organization")
        self.assertEqual((data["done"], data["total"]), (0, 6))
        self.assertEqual(data["steps"][1], {"key": "branch", "title": "Филиал", "status": "todo"})

    def test_confirm_skip_and_resume_from_same_place(self):
        self.api.post(reverse("tenants:onboarding-confirm-organization"))
        self.api.post(reverse("tenants:onboarding-skip", args=["branch"]))

        data = self.api.get(STATE_URL).json()

        self.assertEqual(data["steps"][0]["status"], "done")
        self.assertEqual(data["steps"][1]["status"], "skipped")
        self.assertEqual(data["current"], "directions")

    def test_step_done_outside_wizard_counts(self):
        Branch.objects.create(organization=self.org, name="Центральный")

        data = self.api.get(STATE_URL).json()

        self.assertEqual(data["steps"][1]["status"], "done")

    def test_saving_org_settings_counts_as_organization_step(self):
        self.api.put(
            reverse("tenants:organization-settings"),
            {
                "name": "Новый центр",
                "timezone": "Asia/Almaty",
                "subscription_ending_lessons_threshold": 3,
                "subscription_ending_days_threshold": 7,
                "debt_overdue_days_threshold": 5,
                "group_underfilled_percent_threshold": 50,
            },
            format="json",
        )

        self.assertEqual(self.api.get(STATE_URL).json()["steps"][0]["status"], "done")

    def test_finish(self):
        data = self.api.post(reverse("tenants:onboarding-finish")).json()
        self.assertTrue(data["finished"])

    def test_unknown_step_is_404(self):
        response = self.api.post(reverse("tenants:onboarding-skip", args=["nope"]))
        self.assertEqual(response.status_code, 404)

    def test_only_owner(self):
        admin = User.objects.create_user(
            phone="+77010000002",
            full_name="Admin",
            password="pass12345",
            organization=self.org,
            role=User.Role.ADMIN,
        )
        self.api.force_authenticate(admin)
        self.assertEqual(self.api.get(STATE_URL).status_code, 403)


class RegisterApiTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_register_without_slug_generates_one_and_returns_tokens(self):
        response = APIClient().post(
            reverse("users:register"),
            {
                "org_name": "Студия Грация",
                "full_name": "Айгерим Серикова",
                "phone": "8 701 555 00 11",
                "password": "Str0ng-pass-123",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertIn("access", response.json())
        org = Organization.objects.get(name="Студия Грация")
        self.assertTrue(org.slug.startswith("center-"))
        self.assertEqual(User.objects.get(organization=org).phone, "+77015550011")
