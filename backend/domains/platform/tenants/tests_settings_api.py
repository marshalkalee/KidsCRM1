"""
API экранов настроек frontend2 (TRU-85): organization/settings/ пишет тем же
путём, что веб (OrganizationSettingsForm), OrganizationSerializer не даёт
сменить тариф/settings, рабочие часы филиала проверяются одинаково.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .models import Branch, Organization
from .org_settings import DEFAULT_ORG_SETTINGS

User = get_user_model()
SETTINGS_URL = reverse("tenants:organization-settings")


class SettingsApiBase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(
            name="True Ballet", slug="true-ballet", settings={"onboarding": {"done": True}}
        )
        self.owner = self.make_user("+77010000001", User.Role.OWNER)
        self.manager = self.make_user("+77010000002", User.Role.MANAGER)
        self.api = APIClient()

    def make_user(self, phone, role):
        return User.objects.create_user(
            phone=phone, full_name=role, password="pass12345", organization=self.org, role=role
        )


class OrganizationSettingsApiTests(SettingsApiBase):
    def payload(self, **overrides):
        return {
            "name": "True Ballet Studio",
            "timezone": "Asia/Almaty",
            "subscription_ending_lessons_threshold": 2,
            "subscription_ending_days_threshold": 5,
            "debt_overdue_days_threshold": 10,
            "group_underfilled_percent_threshold": 40,
            **overrides,
        }

    def test_get_returns_defaults_and_timezones(self):
        self.api.force_authenticate(self.owner)

        data = self.api.get(SETTINGS_URL).json()

        self.assertEqual(data["name"], "True Ballet")
        self.assertEqual(
            data["debt_overdue_days_threshold"], DEFAULT_ORG_SETTINGS["debt_overdue_days_threshold"]
        )
        self.assertIn("Asia/Almaty", data["timezones"])

    def test_put_saves_and_keeps_onboarding(self):
        self.api.force_authenticate(self.owner)

        response = self.api.put(SETTINGS_URL, self.payload(), format="json")

        self.assertEqual(response.status_code, 200, response.content)
        self.org.refresh_from_db()
        self.assertEqual(self.org.name, "True Ballet Studio")
        self.assertEqual(self.org.settings["debt_overdue_days_threshold"], 10)
        self.assertEqual(self.org.settings["onboarding"], {"done": True})

    def test_invalid_values_are_400_with_field_errors(self):
        self.api.force_authenticate(self.owner)

        response = self.api.put(
            SETTINGS_URL,
            self.payload(timezone="Mars/Olympus", group_underfilled_percent_threshold=500),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("timezone", response.json())
        self.assertIn("group_underfilled_percent_threshold", response.json())

    def test_only_owner(self):
        self.api.force_authenticate(self.manager)
        self.assertEqual(self.api.get(SETTINGS_URL).status_code, 403)

    def test_organization_patch_cannot_change_plan_or_settings(self):
        self.api.force_authenticate(self.owner)

        self.api.patch(
            "/api/v1/organization/",
            {"plan": "enterprise", "subscription_status": "active", "settings": {}},
            format="json",
        )

        self.org.refresh_from_db()
        self.assertNotEqual(self.org.plan, "enterprise")
        self.assertEqual(self.org.settings, {"onboarding": {"done": True}})


class BranchWorkingHoursApiTests(SettingsApiBase):
    url = reverse("tenants:branch-list")

    def test_new_branch_gets_default_hours(self):
        self.api.force_authenticate(self.owner)

        response = self.api.post(self.url, {"name": "Северный"}, format="json")

        self.assertEqual(response.status_code, 201, response.content)
        hours = response.json()["working_hours"]
        self.assertEqual(hours["mon"], {"closed": False, "open": "09:00", "close": "20:00"})
        self.assertEqual(hours["sun"], {"closed": True})

    def test_close_before_open_is_rejected(self):
        self.api.force_authenticate(self.owner)

        response = self.api.post(
            self.url,
            {"name": "Северный", "working_hours": {"mon": {"open": "18:00", "close": "10:00"}}},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("mon", response.json()["working_hours"])

    def test_archive_via_is_active_keeps_branch(self):
        branch = Branch.objects.create(organization=self.org, name="Старый")
        self.api.force_authenticate(self.owner)

        response = self.api.patch(
            reverse("tenants:branch-detail", args=[branch.pk]), {"is_active": False}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        listing = self.api.get(self.url).json()
        rows = listing["results"] if isinstance(listing, dict) else listing
        self.assertEqual([(b["name"], b["is_active"]) for b in rows], [("Старый", False)])


class RoomsApiTests(SettingsApiBase):
    def test_rooms_filtered_by_branch_and_counted(self):
        from .models import Room

        center = Branch.objects.create(organization=self.org, name="Центр")
        north = Branch.objects.create(organization=self.org, name="Север")
        Room.objects.create(organization=self.org, branch=center, name="Большой")
        Room.objects.create(organization=self.org, branch=center, name="Малый")
        Room.objects.create(organization=self.org, branch=north, name="Один")
        self.api.force_authenticate(self.owner)

        rooms = self.api.get(reverse("tenants:room-list"), {"branch": str(center.pk)}).json()
        branches = self.api.get(reverse("tenants:branch-list")).json()

        rooms = rooms["results"] if isinstance(rooms, dict) else rooms
        branches = branches["results"] if isinstance(branches, dict) else branches
        self.assertEqual(sorted(r["name"] for r in rooms), ["Большой", "Малый"])
        self.assertEqual({b["name"]: b["rooms_count"] for b in branches}, {"Центр": 2, "Север": 1})
