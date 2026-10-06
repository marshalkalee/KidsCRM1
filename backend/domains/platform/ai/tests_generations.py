from unittest import mock

from django.test import TestCase, override_settings

from domains.platform.tenants.models import Organization

from . import generations, services
from .generation_provider import ProviderResult
from .models import AIGeneration

SNAPSHOT = {
    "occupancy": {"summary": {"percent": 61, "occupied": 22}},
    "conversion": {"percent": 18},
}


class GenerationTest(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="AI test", slug="ai-test")

    def generation(self):
        return AIGeneration.objects.create(
            organization=self.organization,
            function="marketing_recommendations",
            prompt_version="1.0.0",
            provider="openai",
            model="test-model",
        )

    def valid_payload(self, title="Продвигайте свободные группы"):
        return {
            "recommendations": [
                {
                    "title": title,
                    "rationale": "Заполняемость ниже желаемого уровня",
                    "action": "Подготовьте предложение для родителей",
                    "priority": "high",
                    "evidence_keys": ["occupancy.summary.percent"],
                }
            ]
        }

    @override_settings(AI_PROVIDER="openai", OPENAI_API_KEY="key", AI_FIXTURE_MODE=False)
    @mock.patch("domains.platform.ai.generations.aggregates.snapshot", return_value=SNAPSHOT)
    @mock.patch("domains.platform.ai.generations.generation_provider.call")
    def test_validated_result_and_usage_are_logged(self, provider, _snapshot):
        provider.return_value = ProviderResult(self.valid_payload(), 120, 35)
        result = generations.run(self.generation().id)
        self.assertEqual(result.status, AIGeneration.Status.SUCCEEDED)
        self.assertEqual((result.input_tokens, result.output_tokens), (120, 35))
        self.assertEqual(result.prompt_version, "1.0.0")
        self.assertEqual(result.result["recommendations"][0]["evidence"][0]["value"], 61)

    @override_settings(AI_PROVIDER="openai", OPENAI_API_KEY="key", AI_FIXTURE_MODE=False)
    @mock.patch("domains.platform.ai.generations.aggregates.snapshot", return_value=SNAPSHOT)
    @mock.patch("domains.platform.ai.generations.generation_provider.call")
    def test_fabricated_number_never_reaches_result(self, provider, _snapshot):
        provider.side_effect = [
            ProviderResult(self.valid_payload("Заполняемость составляет 99 процентов"), 10, 5),
            ProviderResult(self.valid_payload("Заполняемость составляет 99 процентов"), 10, 5),
        ]
        result = generations.run(self.generation().id)
        self.assertEqual(result.status, AIGeneration.Status.SCHEMA_ERROR)
        self.assertEqual(result.result, {})
        self.assertEqual(provider.call_count, 2)

    @override_settings(AI_PROVIDER="openai", OPENAI_API_KEY="key", AI_FIXTURE_MODE=False)
    @mock.patch("domains.platform.ai.generations.aggregates.snapshot", return_value=SNAPSHOT)
    @mock.patch("domains.platform.ai.generations.generation_provider.call")
    def test_invalid_schema_is_retried_then_degraded(self, provider, _snapshot):
        provider.return_value = ProviderResult({"unexpected": True}, 7, 2)
        result = generations.run(self.generation().id)
        self.assertEqual(result.status, AIGeneration.Status.SCHEMA_ERROR)
        self.assertEqual(result.attempts, 2)
        self.assertEqual((result.input_tokens, result.output_tokens), (14, 4))

    @override_settings(AI_PROVIDER="openai", OPENAI_API_KEY="key", AI_FIXTURE_MODE=False)
    @mock.patch("domains.platform.ai.generations.aggregates.snapshot", return_value=SNAPSHOT)
    @mock.patch("domains.platform.ai.generations.generation_provider.call")
    def test_provider_failure_has_own_degradation(self, provider, _snapshot):
        provider.side_effect = services.AIError("provider down")
        result = generations.run(self.generation().id)
        self.assertEqual(result.status, AIGeneration.Status.PROVIDER_UNAVAILABLE)
        self.assertEqual(result.error_code, "provider_unavailable")

    @override_settings(AI_PROVIDER="openai", OPENAI_API_KEY="", AI_FIXTURE_MODE=False)
    @mock.patch("domains.platform.ai.generations.aggregates.snapshot")
    def test_without_key_does_not_collect_or_call_external_api(self, snapshot):
        result = generations.run(self.generation().id)
        self.assertEqual(result.status, AIGeneration.Status.NO_KEY)
        snapshot.assert_not_called()

    @override_settings(AI_PROVIDER="openai", OPENAI_API_KEY="", AI_FIXTURE_MODE=True)
    @mock.patch("domains.platform.ai.generations.aggregates.snapshot", return_value=SNAPSHOT)
    def test_local_fixture_works_without_key(self, _snapshot):
        result = generations.run(self.generation().id)
        self.assertEqual(result.status, AIGeneration.Status.SUCCEEDED)
        self.assertEqual(result.result["recommendations"][0]["evidence"][0]["value"], 61)

    @mock.patch("domains.platform.ai.tasks.run_ai_generation.delay")
    def test_enqueue_only_schedules_background_task(self, delay):
        with self.captureOnCommitCallbacks(execute=True):
            generation = generations.enqueue(self.organization, "marketing_recommendations")
        self.assertEqual(generation.status, AIGeneration.Status.QUEUED)
        delay.assert_called_once_with(str(generation.id))

    @override_settings(AI_PROVIDER="openai", OPENAI_API_KEY="key", AI_FIXTURE_MODE=False)
    @mock.patch("domains.platform.ai.generations.ensure_within_limit")
    def test_limit_has_distinct_state(self, check):
        check.side_effect = generations.AILimitExceeded
        result = generations.run(self.generation().id)
        self.assertEqual(result.status, AIGeneration.Status.LIMIT_EXHAUSTED)

    @override_settings(
        AI_PROVIDER="openai",
        OPENAI_API_KEY="key",
        AI_FIXTURE_MODE=False,
        AI_GENERATION_MAX_INPUT_CHARS=10,
    )
    @mock.patch("domains.platform.ai.generations.aggregates.snapshot", return_value=SNAPSHOT)
    @mock.patch("domains.platform.ai.generations.generation_provider.call")
    def test_request_size_is_limited_before_provider_call(self, provider, _snapshot):
        result = generations.run(self.generation().id)
        self.assertEqual(result.status, AIGeneration.Status.INPUT_TOO_LARGE)
        provider.assert_not_called()
