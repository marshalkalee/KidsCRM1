from datetime import date
from unittest import mock

from django.test import TestCase

from domains.platform.analytics.period import Period
from domains.platform.analytics.promotion import promotion_signals
from domains.platform.analytics.scope import Scope
from domains.platform.leads.models import Lead
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.scheduling.groups.models import Group


class PromotionSignalsTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Promotion", slug="promotion")
        self.branch = Branch.objects.create(organization=self.organization, name="Центр")
        self.direction = Direction.objects.create(organization=self.organization, name="Балет")
        self.group = Group.objects.create(
            organization=self.organization,
            branch=self.branch,
            direction=self.direction,
            name="Балет 7–9",
            capacity=12,
            age_min=7,
            age_max=9,
        )
        self.excluded = Group.objects.create(
            organization=self.organization,
            branch=self.branch,
            direction=self.direction,
            name="Конкурсная группа",
            capacity=8,
            exclude_from_ai_recommendations=True,
        )
        self.period = Period(date(2026, 9, 1), date(2026, 9, 30), "month")
        self.scope = Scope(self.organization, None, [])

    def occupancy(self):
        rows = [
            {
                "id": str(self.group.id),
                "name": self.group.name,
                "branch": self.branch.name,
                "direction": self.direction.name,
                "capacity": 12,
                "occupied": 4,
                "percent": 33,
                "is_underfilled": True,
            },
            {
                "id": str(self.excluded.id),
                "name": self.excluded.name,
                "branch": self.branch.name,
                "direction": self.direction.name,
                "capacity": 8,
                "occupied": 2,
                "percent": 25,
                "is_underfilled": True,
            },
        ]
        return {"groups": rows, "underfilled": rows}

    @mock.patch("domains.platform.analytics.promotion._lead_rows")
    @mock.patch("domains.platform.analytics.promotion.group_occupancy")
    def test_evidence_case_seasonality_and_explicit_exclusion(self, occupancy, leads):
        occupancy.return_value = self.occupancy()
        leads.side_effect = [
            [
                {
                    "branch_id": self.branch.id,
                    "direction_id": self.direction.id,
                    "child_age": 8,
                    "source__name": "Instagram",
                    "status": Lead.Status.PURCHASED,
                },
                {
                    "branch_id": self.branch.id,
                    "direction_id": self.direction.id,
                    "child_age": 8,
                    "source__name": "Instagram",
                    "status": Lead.Status.NEW,
                },
            ],
            [
                {
                    "branch_id": self.branch.id,
                    "direction_id": self.direction.id,
                    "child_age": 8,
                    "source__name": "Рекомендация",
                    "status": Lead.Status.NEW,
                }
            ],
        ]

        result = promotion_signals(self.scope, self.period)

        self.assertEqual(len(result["кандидаты"]), 1)
        candidate = result["кандидаты"][0]
        self.assertEqual(candidate["группа"], "Балет 7–9")
        self.assertEqual(candidate["случай"], "quick_win")
        self.assertEqual(candidate["свободных_мест"], 8)
        self.assertEqual(candidate["заявок_на_направление"], 2)
        self.assertEqual(candidate["конверсия_процент"], 50.0)
        self.assertEqual(candidate["заявок_в_тот_же_месяц_год_назад"], 1)
        self.assertEqual(
            candidate["источники_этого_возраста"], [{"источник": "Instagram", "заявок": 2}]
        )
        self.assertEqual(candidate["сезон"], "высокий сезон набора")

    @mock.patch("domains.platform.analytics.promotion._lead_rows", side_effect=[[], []])
    @mock.patch("domains.platform.analytics.promotion.group_occupancy")
    def test_no_matching_demand_is_build_demand(self, occupancy, _leads):
        occupancy.return_value = self.occupancy()
        candidate = promotion_signals(self.scope, self.period)["кандидаты"][0]
        self.assertEqual(candidate["случай"], "build_demand")
