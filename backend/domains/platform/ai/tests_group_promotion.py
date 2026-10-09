from django.test import TestCase

from domains.platform.tenants.models import Organization

from .models import AIRecommendationState
from .prompts.group_promotion import validate
from .recommendations import dismiss, remember


def candidate():
    return {
        "candidate_key": "candidate-one",
        "группа": "Балет 7–9",
        "филиал": "Центр",
        "направление": "Балет",
        "свободных_мест": 8,
        "заполняемость_процент": 33,
        "заявок_на_направление": 5,
        "купили": 2,
        "конверсия_процент": 40.0,
        "источники_этого_возраста": [{"источник": "Instagram", "заявок": 3}],
        "заявок_в_тот_же_месяц_год_назад": 4,
        "сезон": "высокий сезон набора",
        "случай": "quick_win",
        "системная_проблема_направления_в_филиале": False,
    }


def model_payload(title="Продвигайте группу с готовым спросом"):
    return {
        "recommendations": [
            {
                "candidate_key": "candidate-one",
                "title": title,
                "rationale": "Есть подходящие обращения и свободные места",
                "action": "Запустите предложение через основной источник",
            }
        ]
    }


class GroupPromotionTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="AI", slug="ai-promotion")
        self.snapshot = {"promotion_opportunities": {"кандидаты": [candidate()]}}

    def validated(self):
        return validate(model_payload(), {}, self.snapshot)

    def test_numbers_are_inserted_from_analytics_not_model(self):
        recommendation = self.validated()["recommendations"][0]
        self.assertEqual(
            recommendation["basis"],
            {
                "available_places": 8,
                "occupancy_percent": 33,
                "direction_leads": 5,
                "purchased": 2,
                "conversion_percent": 40.0,
                "same_month_last_year_leads": 4,
                "age_sources": [{"источник": "Instagram", "заявок": 3}],
            },
        )

    def test_model_authored_numbers_are_rejected(self):
        with self.assertRaisesMessage(ValueError, "contain no numbers"):
            validate(model_payload("Заполните 8 свободных мест"), {}, self.snapshot)

    def test_unchanged_recommendation_is_not_repeated_forever(self):
        result = self.validated()
        for _ in range(3):
            self.assertEqual(
                len(remember(self.organization, result, self.snapshot)["recommendations"]), 1
            )
        self.assertEqual(remember(self.organization, result, self.snapshot)["recommendations"], [])

    def test_dismissed_recommendation_does_not_return(self):
        result = self.validated()
        first = remember(self.organization, result, self.snapshot)["recommendations"][0]
        dismiss(self.organization, first["recommendation_id"])
        self.assertEqual(remember(self.organization, result, self.snapshot)["recommendations"], [])
        self.assertEqual(
            AIRecommendationState.objects.get(pk=first["recommendation_id"]).status,
            AIRecommendationState.Status.DISMISSED,
        )
