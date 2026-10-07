from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from domains.platform.tenants.models import Organization
from domains.platform.users.models import User

from .models import AIContentDraft, AIGeneration
from .prompts.content_studio import validate


def candidate():
    return {
        "candidate_key": "group-one",
        "группа": "Балет 7–9",
        "филиал": "Центр",
        "направление": "Балет",
        "расписание": [{"день": "Понедельник", "время": "18:00"}],
        "свободных_мест": 8,
        "заполняемость_процент": 33,
        "заявок_на_направление": 5,
        "конверсия_процент": 40.0,
        "заявок_в_тот_же_месяц_год_назад": 4,
    }


def payload(post_body="Покажем атмосферу обычного занятия без лишних обещаний"):
    return {
        "campaigns": [
            {
                "candidate_key": "group-one",
                "title": "Знакомство с направлением",
                "mechanic": "Предложить родителям познакомиться с группой",
                "rationale": "У группы есть потенциал для нового набора",
            }
        ],
        "plan": [
            {
                "candidate_key": "group-one",
                "moment": "early_week",
                "format": "post",
                "theme": "Знакомство с занятиями",
                "goal": "Получить обращения родителей",
            }
        ],
        "posts": [
            {
                "candidate_key": "group-one",
                "hook": "Ищете занятие для ребёнка?",
                "body": post_body,
                "cta": "Напишите нам, чтобы узнать условия записи",
            }
        ],
        "videos": [
            {
                "candidate_key": "group-one",
                "title": "Один урок изнутри",
                "shots": ["Снимите общий план зала", "Покажите упражнение группы"],
                "caption": "Показываем атмосферу обычного занятия",
            }
        ],
    }


class ContentTemplateTests(TestCase):
    def setUp(self):
        self.snapshot = {"promotion_opportunities": {"кандидаты": [candidate()]}}

    def test_real_group_schedule_and_numbers_are_inserted_by_code(self):
        result = validate(
            payload(),
            {},
            self.snapshot,
            {"language": "ru", "content_type": "both", "content_count": 1},
        )
        post = result["posts"][0]
        self.assertIn("Балет 7–9", post["text"])
        self.assertIn("Понедельник 18:00", post["text"])
        self.assertIn("Свободных мест: 8", post["text"])
        self.assertEqual(post["basis"]["available_places"], 8)
        self.assertEqual(result["content_type"], "both")

    def test_single_post_returns_only_one_post(self):
        source = payload()
        source["posts"].append(source["posts"][0].copy())
        result = validate(
            source,
            {},
            self.snapshot,
            {"language": "ru", "content_type": "post", "content_count": 2},
        )
        self.assertEqual(len(result["posts"]), 2)
        self.assertEqual(result["campaigns"], [])
        self.assertEqual(result["plan"], [])
        self.assertEqual(result["videos"], [])

    def test_single_reel_returns_only_one_video(self):
        result = validate(
            payload(),
            {},
            self.snapshot,
            {"language": "ru", "content_type": "reel", "content_count": 1},
        )
        self.assertEqual(len(result["videos"]), 1)
        self.assertEqual(result["campaigns"], [])
        self.assertEqual(result["plan"], [])
        self.assertEqual(result["posts"], [])

    def test_model_cannot_invent_prices_discounts_or_numbers(self):
        with self.assertRaisesMessage(ValueError, "invented offer or number"):
            validate(
                payload("Только сегодня скидка 20 процентов"),
                {},
                self.snapshot,
                {"language": "ru", "content_type": "post", "content_count": 1},
            )

    def test_model_cannot_repeat_crm_names(self):
        with self.assertRaisesMessage(ValueError, "CRM names"):
            validate(
                payload("Расскажем про филиал Центр"),
                {},
                self.snapshot,
                {"language": "ru", "content_type": "post", "content_count": 1},
            )

    def test_direction_name_is_allowed_in_marketing_copy(self):
        result = validate(
            payload("Покажем, как проходит занятие по балету"),
            {},
            self.snapshot,
            {"language": "ru", "content_type": "post", "content_count": 1},
        )
        self.assertIn("балету", result["posts"][0]["text"])


class ContentStudioAPITests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Content", slug="content")
        self.owner = User.objects.create_user(
            phone="77010000222",
            password="pass",
            full_name="Owner",
            organization=self.organization,
            role=User.Role.OWNER,
        )
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    @mock.patch("domains.platform.ai.tasks.run_ai_generation.delay")
    def test_generation_is_enqueued_with_language_and_content_type(self, delay):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.api.post(
                "/api/v1/ai/content/",
                {
                    "language": "kk",
                    "content_type": "post",
                    "instructions": "Спокойный тон для родителей подростков",
                },
                format="json",
            )
        self.assertEqual(response.status_code, 202, response.data)
        generation = AIGeneration.objects.get(pk=response.data["id"])
        self.assertEqual(
            generation.parameters,
            {
                "language": "kk",
                "content_type": "post",
                "content_count": 3,
                "instructions": "Спокойный тон для родителей подростков",
            },
        )
        delay.assert_called_once_with(str(generation.id))

    def test_generation_instructions_are_limited(self):
        response = self.api.post(
            "/api/v1/ai/content/",
            {"language": "ru", "content_type": "post", "instructions": "x" * 1001},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("instructions", response.data)

    @mock.patch("domains.platform.ai.tasks.run_ai_generation.delay")
    def test_content_count_is_read_from_instructions(self, _delay):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.api.post(
                "/api/v1/ai/content/",
                {
                    "language": "ru",
                    "content_type": "both",
                    "instructions": "Сделай 2 поста и Reels в спокойном тоне",
                },
                format="json",
            )
        self.assertEqual(response.status_code, 202, response.data)
        generation = AIGeneration.objects.get(pk=response.data["id"])
        self.assertEqual(generation.parameters["content_count"], 2)

    @mock.patch("domains.platform.ai.tasks.run_ai_generation.delay")
    def test_language_can_be_requested_in_instructions(self, _delay):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.api.post(
                "/api/v1/ai/content/",
                {
                    "language": "ru",
                    "content_type": "post",
                    "instructions": "Сгенерируй идеи постов на казахском языке",
                },
                format="json",
            )
        self.assertEqual(response.status_code, 202, response.data)
        generation = AIGeneration.objects.get(pk=response.data["id"])
        self.assertEqual(generation.parameters["language"], "kk")

    def test_running_generation_can_be_cancelled(self):
        generation = AIGeneration.objects.create(
            organization=self.organization,
            function="content_studio",
            prompt_version="1.0.1",
            status=AIGeneration.Status.RUNNING,
        )
        response = self.api.post(f"/api/v1/ai/content/{generation.id}/cancel/")
        self.assertEqual(response.status_code, 200, response.data)
        generation.refresh_from_db()
        self.assertEqual(generation.status, AIGeneration.Status.CANCELLED)
        self.assertEqual(generation.error_code, "cancelled")
        self.assertIsNotNone(generation.finished_at)

    def test_completed_generation_cannot_be_cancelled(self):
        generation = AIGeneration.objects.create(
            organization=self.organization,
            function="content_studio",
            prompt_version="1.0.1",
            status=AIGeneration.Status.SUCCEEDED,
        )
        response = self.api.post(f"/api/v1/ai/content/{generation.id}/cancel/")
        self.assertEqual(response.status_code, 409)

    def test_draft_can_be_saved_edited_and_deleted(self):
        generation = AIGeneration.objects.create(
            organization=self.organization,
            function="content_studio",
            prompt_version="1.0.0",
            status=AIGeneration.Status.SUCCEEDED,
            result={"posts": []},
        )
        response = self.api.post(
            "/api/v1/ai/content/drafts/",
            {
                "title": "Неделя балета",
                "language": "ru",
                "payload": {"posts": []},
                "generation": str(generation.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        draft_id = response.data["id"]
        response = self.api.patch(
            f"/api/v1/ai/content/drafts/{draft_id}/",
            {"title": "Обновлённая неделя"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["title"], "Обновлённая неделя")
        self.assertEqual(self.api.delete(f"/api/v1/ai/content/drafts/{draft_id}/").status_code, 204)
        self.assertFalse(AIContentDraft.objects.filter(pk=draft_id).exists())

    def test_other_tenant_cannot_read_or_edit_draft(self):
        other = Organization.objects.create(name="Other", slug="other-content")
        draft = AIContentDraft.objects.create(
            organization=other,
            language="ru",
            title="Private content",
            payload={"posts": []},
        )
        response = self.api.patch(
            f"/api/v1/ai/content/drafts/{draft.id}/",
            {"title": "Stolen content"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        listing = self.api.get("/api/v1/ai/content/")
        self.assertNotIn(str(draft.id), {row["id"] for row in listing.data["drafts"]})

    def test_successful_unsaved_generation_is_kept_in_history(self):
        generation = AIGeneration.objects.create(
            organization=self.organization,
            function="content_studio",
            prompt_version="1.2.0",
            status=AIGeneration.Status.SUCCEEDED,
            parameters={
                "language": "kk",
                "content_type": "post",
                "content_count": 3,
                "instructions": "Жылы үн",
            },
            result={
                "language": "kk",
                "content_type": "post",
                "content_count": 3,
                "posts": [{"text": "Дайын мәтін"}],
            },
        )
        response = self.api.get("/api/v1/ai/content/")
        self.assertEqual(response.status_code, 200, response.data)
        row = next(item for item in response.data["history"] if item["id"] == str(generation.id))
        self.assertEqual(row["content"]["posts"][0]["text"], "Дайын мәтін")
        self.assertEqual(row["instructions"], "Жылы үн")
