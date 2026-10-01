from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APITestCase

from domains.people.clients.models import Child
from domains.platform.analytics.period import Period
from domains.platform.analytics.risk_list import risk_list
from domains.platform.analytics.scope import Scope
from domains.platform.tasks.models import Task
from domains.platform.tasks.services import create_retention_task
from domains.platform.tenants.models import Organization
from domains.platform.users.models import User


class RiskListTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Центр",
            slug="risk-list",
            settings={
                "risk_absence_change_pp_threshold": 20,
                "risk_current_absences_min": 2,
            },
        )
        self.scope = Scope(self.organization, None, [])
        self.period = Period(date(2026, 9, 1), date(2026, 9, 30))
        self.attendance_child = self.child("Алия")
        self.subscription_child = self.child("Мира")
        self.urgent_child = self.child("София")

    def child(self, name):
        return Child.objects.create(
            organization=self.organization,
            full_name=name,
            birth_date=date(2018, 1, 1),
        )

    def attendance_row(self, child, *, change=35, absences=3):
        return {
            "id": str(child.id),
            "name": child.full_name,
            "marked": 4,
            "attended": 4 - absences,
            "absences": absences,
            "attendance_rate": 25,
            "absence_rate": 75,
            "baseline": {"marked": 8, "absences": 1, "absence_rate": 12.5},
            "has_baseline": True,
            "absence_change_pp": change,
            "trend": "rising",
        }

    @patch("domains.platform.analytics.risk_list.debt_by_child")
    @patch("domains.platform.analytics.risk_list.renewal_risk_by_child")
    @patch("domains.platform.analytics.risk_list.child_attendance_deviation")
    def test_combines_canonical_signals_and_sorts_urgent_first(self, attendance, renewal, debts):
        attendance.return_value = [self.attendance_row(self.attendance_child)]
        renewal.return_value = {
            self.subscription_child.id: {"state": "ending", "ends_on": "2026-10-03"},
            self.urgent_child.id: {"state": "expired", "ends_on": "2026-09-20"},
        }
        debts.return_value = {self.urgent_child.id: Decimal("15000")}

        data = risk_list(self.scope, self.period)

        self.assertEqual(data["summary"]["total"], 3)
        self.assertEqual(data["summary"]["urgent"], 1)
        self.assertEqual(data["items"][0]["id"], str(self.urgent_child.id))
        self.assertEqual(data["items"][0]["signals"], ["subscription", "debt"])
        renewal.assert_called_once()
        debts.assert_called_once()

    @patch("domains.platform.analytics.risk_list.debt_by_child", return_value={})
    @patch("domains.platform.analytics.risk_list.renewal_risk_by_child", return_value={})
    @patch("domains.platform.analytics.risk_list.child_attendance_deviation")
    def test_configured_absence_threshold_is_applied(self, attendance, _renewal, _debts):
        attendance.return_value = [
            self.attendance_row(self.attendance_child, change=19, absences=3)
        ]
        self.assertEqual(risk_list(self.scope, self.period)["items"], [])


class RetentionTaskTests(TestCase):
    def test_task_is_idempotent_and_assigned_to_actor(self):
        organization = Organization.objects.create(name="Центр", slug="retention-task")
        owner = User.objects.create_user(
            organization=organization,
            phone="+77015550001",
            password="x",
            full_name="Владелец",
            role=User.Role.OWNER,
        )
        child = Child.objects.create(
            organization=organization,
            full_name="Алия",
            birth_date=date(2018, 1, 1),
        )

        first, created = create_retention_task(
            child=child, actor=owner, signals=["attendance", "debt"]
        )
        second, created_again = create_retention_task(
            child=child, actor=owner, signals=["attendance", "debt"]
        )

        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.id, second.id)
        self.assertEqual(first.type, Task.Type.RETENTION)
        self.assertEqual(first.assigned_to, owner)


class RiskListActionApiTests(APITestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Центр", slug="risk-list-api")
        self.owner = User.objects.create_user(
            organization=self.organization,
            phone="+77015550002",
            password="x",
            full_name="Владелец",
            role=User.Role.OWNER,
        )
        self.child = Child.objects.create(
            organization=self.organization,
            full_name="Алия",
            birth_date=date(2018, 1, 1),
        )
        self.client.force_authenticate(self.owner)

    @patch("domains.platform.analytics.views.risk_list")
    def test_creates_retention_task_from_report(self, mocked_risk_list):
        mocked_risk_list.return_value = {
            "items": [{"id": str(self.child.id), "signals": ["attendance", "debt"]}]
        }
        response = self.client.post(f"/api/v1/analytics/risk-list/{self.child.id}/task/")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(
            Task.objects.filter(
                organization=self.organization,
                type=Task.Type.RETENTION,
                assigned_to=self.owner,
            ).exists()
        )
