"""ИИ-помощник: Claude подменён — проверяем, что уходит в модель, как
разбирается ответ и что ошибки превращаются в понятные сообщения."""

import json
from types import SimpleNamespace
from unittest import mock

import anthropic
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from domains.platform.leads.models import LeadSource
from domains.platform.leads.services import create_lead
from domains.platform.tenants.models import Direction, Organization
from domains.platform.users.models import User

from . import services


def connection_error():
    # Конструктор ошибки SDK требует объект запроса его HTTP-клиента —
    # для теста хватает экземпляра без него.
    error = anthropic.APIConnectionError.__new__(anthropic.APIConnectionError)
    Exception.__init__(error, "нет сети")
    return error


def fake_response(payload, stop_reason="end_turn"):
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return SimpleNamespace(
        stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)]
    )


def patched_client(response=None, error=None):
    create = mock.Mock(return_value=response, side_effect=error)
    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    return mock.patch.object(services, "_client", return_value=client), create


@override_settings(ANTHROPIC_API_KEY="test-key", AI_MODEL="claude-opus-5")
class AIFixtures(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="tb")
        self.ballet = Direction.objects.create(organization=self.org, name="Классический балет")
        Direction.objects.create(organization=self.org, name="Гимнастика")
        self.owner = User.objects.create_user(
            phone="77010000001",
            password="pass",
            full_name="Владелец",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.client_api = APIClient()
        self.client_api.force_authenticate(user=self.owner)


class LeadFromTextTests(AIFixtures):
    MESSAGE = (
        "Здравствуйте! Увидела вас в инстаграме. Дочке Алие 6 лет, хотим на балет. "
        "Меня зовут Айгерим, 8 707 111 22 33"
    )

    def test_fields_mapped_to_org_dictionaries(self):
        payload = {
            "parent_name": "Айгерим",
            "phone": "8 707 111 22 33",
            "child_name": "Алия",
            "child_age": 6,
            "direction": "Классический балет",
            "source": "Instagram",
            "summary": "Хотят на балет, девочке 6 лет.",
        }
        patch, create = patched_client(fake_response(payload))
        with patch:
            response = self.client_api.post(
                "/api/v1/ai/lead-from-text/", {"text": self.MESSAGE}, format="json"
            )
        self.assertEqual(response.status_code, 200, response.data)
        instagram = LeadSource.objects.get(organization=self.org, name="Instagram")
        self.assertEqual(response.data["phone"], "+77071112233")
        self.assertEqual(response.data["direction"], str(self.ballet.id))
        self.assertEqual(response.data["source"], str(instagram.id))
        self.assertEqual((response.data["child_name"], response.data["child_age"]), ("Алия", 6))
        # В модель уходят справочники организации, ответ — строго по схеме с их значениями.
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs["model"], "claude-opus-5")
        schema = kwargs["output_config"]["format"]["schema"]
        self.assertIn("Классический балет", schema["properties"]["direction"]["enum"])
        self.assertIn("Instagram", schema["properties"]["source"]["enum"])
        self.assertEqual(kwargs["fallbacks"], "default")
        self.assertIn(self.MESSAGE, kwargs["messages"][0]["content"])

    def test_unknown_values_become_empty(self):
        payload = {
            "parent_name": "",
            "phone": "не помню",
            "child_name": "",
            "child_age": 0,
            "direction": "",
            "source": "",
            "summary": "",
        }
        patch, _ = patched_client(fake_response(payload))
        with patch:
            data = self.client_api.post(
                "/api/v1/ai/lead-from-text/", {"text": "Сколько стоит?"}, format="json"
            ).data
        self.assertEqual(
            (data["direction"], data["source"], data["child_age"], data["phone"]),
            (None, None, None, "не помню"),
        )

    def test_empty_and_too_long_text(self):
        self.assertEqual(
            self.client_api.post(
                "/api/v1/ai/lead-from-text/", {"text": " "}, format="json"
            ).status_code,
            400,
        )
        long = "а" * (services.MAX_INPUT_CHARS + 1)
        self.assertEqual(
            self.client_api.post(
                "/api/v1/ai/lead-from-text/", {"text": long}, format="json"
            ).status_code,
            400,
        )

    def test_refusal_and_api_errors_are_friendly(self):
        cases = [
            (fake_response("{}", stop_reason="refusal"), None, "не стал"),
            (
                None,
                connection_error(),
                "Нет связи",
            ),
            (fake_response("не json"), None, "неразборчиво"),
        ]
        for response, error, text in cases:
            patch, _ = patched_client(response, error)
            with patch:
                result = self.client_api.post(
                    "/api/v1/ai/lead-from-text/", {"text": "привет"}, format="json"
                )
            self.assertEqual(result.status_code, 400)
            self.assertIn(text, result.data["detail"])


class LeadMessageTests(AIFixtures):
    def setUp(self):
        super().setUp()
        self.lead = create_lead(
            organization=self.org,
            actor=self.owner,
            parent_name="Айгерим",
            phone="+77071112233",
            child_name="Алия",
            child_age=6,
            direction=self.ballet,
        )
        self.lead.comments.create(
            organization=self.org, author=self.owner, text="Удобно по субботам утром"
        )

    def test_message_uses_lead_facts_without_phone(self):
        patch, create = patched_client(fake_response({"text": "Здравствуйте, Айгерим! ..."}))
        with patch:
            response = self.client_api.post(
                f"/api/v1/ai/leads/{self.lead.id}/message/",
                {"goal": "invite_trial", "language": "kk"},
                format="json",
            )
        self.assertEqual(
            (response.status_code, response.data["text"]), (200, "Здравствуйте, Айгерим! ...")
        )
        prompt = create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("Удобно по субботам утром", prompt)
        self.assertIn("Классический балет", prompt)
        self.assertIn("казахском", prompt)
        self.assertNotIn("7071112233", prompt)  # телефон в модель не отправляем

    def test_bad_goal_or_language(self):
        url = f"/api/v1/ai/leads/{self.lead.id}/message/"
        self.assertEqual(
            self.client_api.post(url, {"goal": "x", "language": "ru"}, format="json").status_code,
            400,
        )
        self.assertEqual(
            self.client_api.post(
                url, {"goal": "thinking", "language": "de"}, format="json"
            ).status_code,
            400,
        )

    def test_foreign_lead_not_found(self):
        other = Organization.objects.create(name="Чужой", slug="other")
        other_owner = User.objects.create_user(
            phone="77090000001",
            password="pass",
            full_name="Чужой",
            organization=other,
            role=User.Role.OWNER,
        )
        client = APIClient()
        client.force_authenticate(user=other_owner)
        response = client.post(
            f"/api/v1/ai/leads/{self.lead.id}/message/",
            {"goal": "thinking", "language": "ru"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)


class AIAccessTests(AIFixtures):
    def test_status_and_roles(self):
        self.assertTrue(self.client_api.get("/api/v1/ai/status/").data["enabled"])
        teacher = User.objects.create_user(
            phone="77010000009",
            password="pass",
            full_name="Учитель",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        client = APIClient()
        client.force_authenticate(user=teacher)
        self.assertEqual(client.get("/api/v1/ai/status/").status_code, 403)

    @override_settings(ANTHROPIC_API_KEY="")
    def test_disabled_without_key(self):
        self.assertFalse(self.client_api.get("/api/v1/ai/status/").data["enabled"])
        response = self.client_api.post(
            "/api/v1/ai/lead-from-text/", {"text": "привет"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("не настроен", response.data["detail"])


def openai_response(payload, refusal=None, finish_reason="stop"):
    content = None if refusal else json.dumps(payload, ensure_ascii=False)
    message = SimpleNamespace(content=content, refusal=refusal)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)])


def patched_openai(response=None, error=None):
    create = mock.Mock(return_value=response, side_effect=error)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return mock.patch.object(services, "_openai_client", return_value=client), create


@override_settings(
    AI_PROVIDER="openai", OPENAI_API_KEY="sk-test", OPENAI_MODEL="gpt-test", ANTHROPIC_API_KEY=""
)
class OpenAIProviderTests(AIFixtures):
    def test_lead_from_text_via_openai(self):
        payload = {
            "parent_name": "Айгерим",
            "phone": "87071112233",
            "child_name": "Алия",
            "child_age": 6,
            "direction": "Классический балет",
            "source": "",
            "summary": "",
        }
        patch, create = patched_openai(openai_response(payload))
        with patch:
            response = self.client_api.post(
                "/api/v1/ai/lead-from-text/", {"text": "балет, 6 лет"}, format="json"
            )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            (response.data["phone"], response.data["direction"]),
            ("+77071112233", str(self.ballet.id)),
        )
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-test")
        self.assertTrue(kwargs["response_format"]["json_schema"]["strict"])
        self.assertEqual(kwargs["messages"][0]["role"], "system")

    def test_openai_refusal_and_bad_key(self):
        import openai

        patch, _ = patched_openai(openai_response({}, refusal="нет"))
        with patch:
            result = self.client_api.post(
                "/api/v1/ai/lead-from-text/", {"text": "x"}, format="json"
            )
        self.assertIn("не стал", result.data["detail"])
        error = openai.AuthenticationError.__new__(openai.AuthenticationError)
        Exception.__init__(error, "bad key")
        patch, _ = patched_openai(error=error)
        with patch:
            result = self.client_api.post(
                "/api/v1/ai/lead-from-text/", {"text": "x"}, format="json"
            )
        self.assertIn("OPENAI_API_KEY", result.data["detail"])

    def test_enabled_by_openai_key(self):
        self.assertTrue(self.client_api.get("/api/v1/ai/status/").data["enabled"])
        with override_settings(OPENAI_API_KEY=""):
            self.assertFalse(self.client_api.get("/api/v1/ai/status/").data["enabled"])
