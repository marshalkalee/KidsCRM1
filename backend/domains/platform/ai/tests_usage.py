"""Учёт расхода ИИ, лимит центра и опция (TRU-160)."""

import datetime
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from domains.platform.users.models import User

from . import chat, generations, usage
from .generation_provider import ProviderResult
from .models import AIGeneration, AIUsage
from .tests import AIFixtures, openai_response, patched_openai

LEAD = {
    "parent_name": "Айгерим",
    "phone": "87071112233",
    "child_name": "Алия",
    "child_age": 6,
    "direction": "Классический балет",
    "source": "",
    "summary": "",
}

OPENAI = {
    "AI_PROVIDER": "openai",
    "OPENAI_API_KEY": "sk-test",
    "OPENAI_MODEL": "gpt-4o-mini",
    "OPENAI_CHAT_MODEL": "gpt-4o",
    "ANTHROPIC_API_KEY": "",
    "AI_USD_KZT": 500.0,
    "AI_MONTHLY_LIMIT_KZT": 1000,
    "AI_FIXTURE_MODE": False,
}


def with_usage(response, prompt_tokens, completion_tokens):
    response.usage = SimpleNamespace(
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
    )
    return response


def spend(organization, usd, *, feature="lead_from_text", when=None):
    row = AIUsage.objects.create(
        organization=organization, feature=feature, model="gpt-4o", cost_usd=Decimal(str(usd))
    )
    if when:
        AIUsage.objects.filter(pk=row.pk).update(created_at=when)
    return row


@override_settings(**OPENAI)
class UsageRecordingTests(AIFixtures):
    def test_cost_is_computed_from_price_table(self):
        # gpt-4o-mini: $0,15 / $0,60 за 1 млн токенов.
        self.assertEqual(usage.cost_usd("gpt-4o-mini", 1_000_000, 1_000_000), Decimal("0.75"))
        self.assertEqual(usage.cost_usd("неизвестная", 1000, 1000), Decimal(0))

    def test_short_task_is_recorded_with_tokens_and_cost(self):
        patcher, _ = patched_openai(with_usage(openai_response(LEAD), 2000, 400))
        with patcher:
            response = self.client_api.post(
                "/api/v1/ai/lead-from-text/", {"text": "Здравствуйте"}, format="json"
            )
        self.assertEqual(response.status_code, 200)
        row = AIUsage.objects.get(organization=self.org)
        self.assertEqual(row.feature, "lead_from_text")
        self.assertEqual(row.model, "gpt-4o-mini")
        self.assertEqual((row.input_tokens, row.output_tokens), (2000, 400))
        self.assertEqual(row.cost_usd, Decimal("0.000540"))

    def test_paid_but_failed_answer_is_still_recorded(self):
        # Отказ модели оплачен — расход не должен теряться вместе с ошибкой.
        refused = with_usage(openai_response(None, refusal="нет"), 1500, 10)
        patcher, _ = patched_openai(refused)
        with patcher:
            response = self.client_api.post(
                "/api/v1/ai/lead-from-text/", {"text": "Здравствуйте"}, format="json"
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(AIUsage.objects.get(organization=self.org).input_tokens, 1500)

    def test_chat_records_every_tool_round(self):
        call = SimpleNamespace(
            id="c1", function=SimpleNamespace(name="get_overview", arguments="{}")
        )
        first = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="", refusal=None, tool_calls=[call])
                )
            ],
            usage=SimpleNamespace(prompt_tokens=5000, completion_tokens=50),
        )
        second = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="Готово", refusal=None, tool_calls=[])
                )
            ],
            usage=SimpleNamespace(prompt_tokens=6000, completion_tokens=200),
        )
        patcher, create = patched_openai()
        create.side_effect = [first, second]
        with patcher, mock.patch.object(chat, "run_tool", return_value="{}"):
            chat.ask(self.owner, [{"role": "user", "content": "Как дела в центре?"}])
        rows = AIUsage.objects.filter(organization=self.org, feature="chat")
        self.assertEqual(rows.count(), 2)
        self.assertEqual(sum(r.input_tokens for r in rows), 11000)


@override_settings(**OPENAI)
class LimitTests(AIFixtures):
    def test_exhausted_limit_answers_with_text_and_does_not_call_model(self):
        spend(self.org, 2)  # 2 $ × 500 = 1000 ₸ — ровно лимит
        patcher, create = patched_openai(openai_response(LEAD))
        with patcher:
            response = self.client_api.post(
                "/api/v1/ai/lead-from-text/", {"text": "Здравствуйте"}, format="json"
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Лимит ИИ на этот месяц исчерпан", response.data["detail"])
        self.assertIn("обновится 1 ", response.data["detail"])
        create.assert_not_called()

    def test_own_limit_overrides_platform_default(self):
        spend(self.org, 2)
        self.org.ai_monthly_limit_kzt = 5000
        self.org.save(update_fields=["ai_monthly_limit_kzt"])
        usage.ensure_within_limit(self.org)  # не бросает

    def test_previous_month_does_not_count(self):
        spend(self.org, 10, when=timezone.now() - datetime.timedelta(days=40))
        usage.ensure_within_limit(self.org)
        self.assertEqual(usage.spent_kzt(self.org), 0)

    def test_enqueue_over_limit_does_not_schedule_generation(self):
        spend(self.org, 2)
        with mock.patch("domains.platform.ai.tasks.run_ai_generation.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                generation = generations.enqueue(self.org, "marketing_recommendations")
        self.assertEqual(generation.status, AIGeneration.Status.LIMIT_EXHAUSTED)
        self.assertIn("обновится", generation.error_detail)
        delay.assert_not_called()

    @mock.patch(
        "domains.platform.ai.generations.aggregates.snapshot",
        return_value={"occupancy": {"percent": 61}},
    )
    @mock.patch("domains.platform.ai.generations.generation_provider.call")
    def test_generation_records_each_attempt_against_journal(self, provider, _snapshot):
        provider.return_value = ProviderResult({"unexpected": True}, 700, 20)
        generation = AIGeneration.objects.create(
            organization=self.org,
            function="marketing_recommendations",
            prompt_version="1.0.0",
            provider="openai",
            model="gpt-5.4",
        )
        result = generations.run(generation.id)
        self.assertEqual(result.status, AIGeneration.Status.SCHEMA_ERROR)
        rows = AIUsage.objects.filter(generation=generation)
        self.assertEqual(rows.count(), 2)
        # Учёт совпадает с журналом генераций.
        self.assertEqual(sum(r.input_tokens for r in rows), result.input_tokens)
        self.assertEqual(sum(r.output_tokens for r in rows), result.output_tokens)


@override_settings(**OPENAI)
class OptionTests(AIFixtures):
    def disable(self):
        self.org.ai_enabled = False
        self.org.save(update_fields=["ai_enabled"])

    def test_disabled_option_hides_ai_and_closes_api(self):
        self.disable()
        self.assertFalse(self.client_api.get("/api/v1/ai/status/").data["enabled"])
        patcher, create = patched_openai(openai_response(LEAD))
        with patcher:
            for method, url in [
                ("post", "/api/v1/ai/lead-from-text/"),
                ("post", "/api/v1/ai/chat/"),
                ("get", "/api/v1/ai/conversations/"),
                ("post", "/api/v1/ai/daily-plan/"),
            ]:
                response = getattr(self.client_api, method)(url, {"text": "x"}, format="json")
                self.assertEqual(response.status_code, 403, url)
        create.assert_not_called()

    def test_usage_screen_is_owner_only(self):
        spend(self.org, 1, feature="chat")
        spend(self.org, Decimal("0.5"), feature="lead_message")
        spend(self.org, Decimal("0.2"), feature="reminders")
        data = self.client_api.get("/api/v1/ai/usage/").data
        self.assertEqual((data["spent_kzt"], data["limit_kzt"]), (850, 1000))
        self.assertFalse(data["exhausted"])
        self.assertEqual(
            [(g["key"], g["calls"], g["cost_kzt"]) for g in data["by_feature"]],
            [("chat", 1, 500), ("short_tasks", 2, 350)],
        )
        self.assertNotIn("cost", data["by_feature"][0])  # только ₸, без внутренних $
        admin = User.objects.create_user(
            phone="77010000002",
            password="pass",
            full_name="Админ",
            organization=self.org,
            role=User.Role.ADMIN,
        )
        client = APIClient()
        client.force_authenticate(user=admin)
        self.assertEqual(client.get("/api/v1/ai/usage/").status_code, 403)

    def test_platform_report_lists_spend_per_organization(self):
        spend(self.org, Decimal("1.5"))
        out = StringIO()
        call_command("ai_usage_report", stdout=out)
        self.assertIn("True Ballet", out.getvalue())
        self.assertIn("750", out.getvalue())
