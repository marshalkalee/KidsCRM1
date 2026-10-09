"""Еженедельный дайджест (TRU-163)."""

import datetime
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from domains.platform.users.models import User

from . import digest, services
from .generation_provider import ProviderResult
from .models import AIDigest, AIUsage
from .tests import AIFixtures
from .tests_usage import OPENAI

ALMATY = ZoneInfo("Asia/Almaty")


def snapshot(percent=42, occupied=40):
    return {
        "occupancy": {
            "итого": {"occupied": occupied, "capacity": 80},
            "группы": [
                {"группа": "Балет 4–9", "филиал": "Алмалы", "занято": 5, "процент": percent},
                {"группа": "Растяжка 5–10", "филиал": "Орбита", "занято": 2, "процент": 13},
            ],
        },
        "money": {"Выручка": {"было": Decimal("125000.00")}},
    }


def recommendation(title, keys, priority="medium"):
    return {
        "title": title,
        "rationale": "Есть свободные места",
        "action": "Запустите пост про пробное",
        "priority": priority,
        "evidence_keys": keys,
    }


def answer(*rows):
    return ProviderResult({"recommendations": list(rows)}, 900, 150)


BALLET = "occupancy.группы[0].процент"
STRETCH = "occupancy.группы[1].процент"


@override_settings(**OPENAI)
class DigestBuildTests(AIFixtures):
    def build(self, provider_answer, snap=None, language="ru"):
        item = AIDigest.objects.create(
            organization=self.org,
            week_start=datetime.date(2026, 10, 5),
            trigger="schedule",
            language=language,
        )
        with (
            mock.patch("domains.platform.ai.aggregates.snapshot", return_value=snap or snapshot()),
            mock.patch(
                "domains.platform.ai.generations.generation_provider.call",
                **(
                    {"side_effect": provider_answer}
                    if isinstance(provider_answer, Exception)
                    else {"return_value": provider_answer}
                ),
            ) as call,
        ):
            return digest.build(item.id), call

    def test_ready_digest_has_highlights_with_numbers_from_aggregates(self):
        rows = [recommendation(f"Совет {n}", [BALLET]) for n in "абвг"]
        rows.append(recommendation("Набор в растяжку", [STRETCH], priority="high"))
        item, _ = self.build(answer(*rows[:5]))
        self.assertEqual(item.status, AIDigest.Status.READY)
        top = item.content["highlights"]
        self.assertEqual(len(top), digest.HIGHLIGHTS)
        # Главное сверху: высокий приоритет — первым.
        self.assertEqual(top[0]["title"], "Набор в растяжку")
        evidence = top[0]["evidence"][0]
        self.assertEqual(evidence["value"], 13)
        self.assertEqual(
            evidence["label"], "Заполняемость · Растяжка 5–10, Орбита: заполняемость, %"
        )
        self.assertIsNone(item.content["changes"])  # сравнивать не с чем
        # Расход учтён и связан с генерацией.
        self.assertEqual(AIUsage.objects.filter(feature="marketing_recommendations").count(), 1)

    def test_money_facts_are_numbers(self):
        item, _ = self.build(answer(recommendation("Выручка", ["money.Выручка.было"])))
        self.assertEqual(item.status, AIDigest.Status.READY)
        self.assertEqual(item.content["highlights"][0]["evidence"][0]["value"], 125000)

    def test_digest_language_reaches_model_and_localizes_fact_labels(self):
        item, call = self.build(answer(recommendation("Топты толтырыңыз", [BALLET])), language="kk")
        self.assertEqual(item.language, "kk")
        self.assertEqual(item.content["language"], "kk")
        self.assertTrue(
            item.content["highlights"][0]["evidence"][0]["label"].startswith("Толымдылық")
        )
        self.assertIn("қазақ тілінде", call.call_args.kwargs["user"])

    def test_small_center_gets_honest_empty_state_without_model(self):
        item, call = self.build(
            answer(recommendation("Совет", [BALLET])), snap=snapshot(occupied=6)
        )
        self.assertEqual(item.status, AIDigest.Status.INSUFFICIENT_DATA)
        self.assertEqual(item.content, {"active_children": 6, "needed": digest.MIN_ACTIVE_CHILDREN})
        call.assert_not_called()

    def test_same_situation_next_week_says_nothing_changed(self):
        first, _ = self.build(answer(recommendation("Продвигайте балет", [BALLET])))
        # Модель сформулировала иначе, но совет о том же и цифры те же.
        second, _ = self.build(answer(recommendation("Балету нужны дети", [BALLET])))
        changes = second.content["changes"]
        self.assertTrue(changes["unchanged"])
        self.assertEqual(changes["since"], first.week_start.isoformat())

    def test_changes_show_new_advice_and_moved_numbers(self):
        self.build(answer(recommendation("Продвигайте балет", [BALLET])))
        second, _ = self.build(
            answer(
                recommendation("Продвигайте балет", [BALLET]),
                recommendation("Растяжка пустует", [STRETCH]),
            ),
            snap=snapshot(percent=58),
        )
        changes = second.content["changes"]
        self.assertFalse(changes["unchanged"])
        self.assertEqual(changes["new"], ["Растяжка пустует"])
        self.assertEqual([(v["before"], v["after"]) for v in changes["values"]], [(42, 58)])

    def test_provider_failure_keeps_previous_digest(self):
        ready, _ = self.build(answer(recommendation("Продвигайте балет", [BALLET])))
        failed, _ = self.build(services.AIError("ИИ временно недоступен."))
        self.assertEqual(failed.status, AIDigest.Status.FAILED)
        self.assertIn("повторим завтра", failed.error_detail)
        data = self.client_api.get("/api/v1/ai/digests/").data
        self.assertEqual(data["latest"]["id"], str(ready.id))
        self.assertEqual(data["notice"]["status"], AIDigest.Status.FAILED)

    def test_fact_label_for_series(self):
        snap = {"seasonality": {"Новых заявок": [{"месяц": "2026-09", "значение": 36}]}}
        self.assertEqual(
            digest.fact_label(snap, "seasonality.Новых заявок[0].значение"),
            "Сезонность · Новых заявок · 2026-09",
        )

    def test_fact_label_for_promotion_candidates_has_no_ids(self):
        snap = {
            "promotion_opportunities": {
                "кандидаты": [
                    {"ref": "d397137c375b6e8c", "группа": "Растяжка 5–10", "филиал": "Орбита",
                     "заполняемость_процент": 13},
                ]
            }
        }  # fmt: skip
        self.assertEqual(
            digest.fact_label(snap, "promotion_opportunities.кандидаты[0].заполняемость_процент"),
            "Продвижение · Растяжка 5–10, Орбита: заполняемость, %",
        )

    def test_fact_label_for_nested_keys(self):
        self.assertEqual(
            digest.fact_label(snapshot(), "occupancy.итого.occupied"),
            "Заполняемость · весь центр: занято мест",
        )

    def test_fact_label_never_exposes_internal_candidate_key(self):
        candidate_key = "edf921beb0c2995b"
        snap = {
            "promotion_opportunities": {
                "кандидаты": [
                    {
                        "candidate_key": candidate_key,
                        "группа": "Хореография 6–10",
                        "филиал": "Алмалы",
                        "приоритет": "high",
                    }
                ]
            }
        }

        label = digest.fact_label(
            snap,
            "promotion_opportunities.кандидаты[0].приоритет",
        )

        self.assertNotIn(candidate_key, label)
        self.assertIn("Хореография 6–10", label)
        self.assertIn("Алмалы", label)


@override_settings(**OPENAI)
class DigestApiTests(AIFixtures):
    def setUp(self):
        super().setUp()
        self.delay = mock.patch("domains.platform.ai.tasks.build_ai_digest.delay").start()
        self.addCleanup(mock.patch.stopall)

    def refresh(self, client=None, data=None):
        with self.captureOnCommitCallbacks(execute=True):
            return (client or self.client_api).post(
                "/api/v1/ai/digests/", data or {}, format="json"
            )

    def test_refresh_saves_current_interface_language(self):
        response = self.refresh(data={"language": "kk"})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(AIDigest.objects.get().language, "kk")
        self.assertEqual(response.data["building"]["language"], "kk")

    def test_refresh_rejects_unknown_language(self):
        response = self.refresh(data={"language": "de"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AIDigest.objects.exists())

    def test_list_only_returns_digest_in_requested_language(self):
        AIDigest.objects.create(
            organization=self.org,
            week_start=datetime.date(2026, 10, 5),
            trigger=AIDigest.Trigger.SCHEDULE,
            language="ru",
            status=AIDigest.Status.READY,
            ready_at=timezone.now(),
        )
        response = self.client_api.get("/api/v1/ai/digests/", {"language": "kk"})
        self.assertIsNone(response.data["latest"])
        self.assertEqual(response.data["archive"], [])

    def test_repeated_refresh_does_not_multiply_generations(self):
        first = self.refresh()
        self.assertEqual(first.status_code, 202)
        self.assertTrue(first.data["created"])
        second = self.refresh()
        self.assertFalse(second.data["created"])
        self.assertEqual(second.data["building"]["id"], first.data["building"]["id"])
        self.assertEqual(self.delay.call_count, 1)

    def test_stuck_build_is_failed_and_refresh_starts_a_new_one(self):
        stuck = self.refresh().data["building"]["id"]
        AIDigest.objects.filter(pk=stuck).update(
            created_at=datetime.datetime.now(datetime.UTC) - digest.STUCK_AFTER * 2
        )
        data = self.client_api.get("/api/v1/ai/digests/").data
        self.assertIsNone(data["building"])
        self.assertEqual(data["notice"]["status"], AIDigest.Status.FAILED)
        again = self.refresh()
        self.assertTrue(again.data["created"])
        self.assertNotEqual(again.data["building"]["id"], stuck)

    def test_refresh_right_after_previous_is_refused_with_text(self):
        self.refresh()
        AIDigest.objects.update(status=AIDigest.Status.READY)
        response = self.refresh()
        self.assertEqual(response.status_code, 400)
        self.assertIn("мин назад", response.data["detail"])

    def test_refresh_over_limit_is_refused_with_text(self):
        AIUsage.objects.create(organization=self.org, feature="chat", model="gpt-4o", cost_usd=5)
        response = self.refresh()
        self.assertEqual(response.status_code, 400)
        self.assertIn("Лимит ИИ", response.data["detail"])
        self.assertFalse(AIDigest.objects.exists())

    def test_owner_and_manager_only_and_only_with_option(self):
        admin = User.objects.create_user(
            phone="77010000005", password="p", full_name="Админ",
            organization=self.org, role=User.Role.ADMIN,
        )  # fmt: skip
        client = APIClient()
        client.force_authenticate(user=admin)
        self.assertEqual(client.get("/api/v1/ai/digests/").status_code, 403)
        self.org.ai_enabled = False
        self.org.save(update_fields=["ai_enabled"])
        self.assertEqual(self.client_api.get("/api/v1/ai/digests/").status_code, 403)

    def test_notification_after_ready_digest(self):
        from django.utils import timezone

        AIDigest.objects.create(
            organization=self.org, week_start=datetime.date(2026, 10, 5), trigger="schedule",
            status=AIDigest.Status.READY, ready_at=timezone.now(),
        )  # fmt: skip
        items = {i["kind"]: i for i in self.client_api.get("/api/v1/notifications/").data["items"]}
        self.assertEqual(items["ai_digest"]["count"], 1)
        self.assertTrue(items["ai_digest"]["unread"])
        self.assertEqual(items["ai_digest"]["link"], "/digest")


@override_settings(**OPENAI)
class DigestScheduleTests(AIFixtures):
    def setUp(self):
        super().setUp()
        self.delay = mock.patch("domains.platform.ai.tasks.build_ai_digest.delay").start()
        self.addCleanup(mock.patch.stopall)

    def at(self, day, hour):
        # 5 октября 2026 — понедельник.
        return datetime.datetime(2026, 10, day, hour, 0, tzinfo=ALMATY)

    def test_monday_morning_by_center_time(self):
        self.assertEqual(digest.dispatch(self.at(5, 8)), 0)
        self.assertEqual(digest.dispatch(self.at(5, 9)), 1)
        # Час спустя — уже есть, второй не ставится.
        self.assertEqual(digest.dispatch(self.at(5, 10)), 0)
        item = AIDigest.objects.get()
        self.assertEqual(item.week_start, datetime.date(2026, 10, 5))
        self.assertEqual(item.trigger, AIDigest.Trigger.SCHEDULE)

    def test_day_and_hour_from_org_settings(self):
        self.org.settings = {"digest_weekday": 2, "digest_hour": 18}
        self.org.save(update_fields=["settings"])
        self.assertEqual(digest.dispatch(self.at(7, 17)), 0)
        self.assertEqual(digest.dispatch(self.at(7, 18)), 1)

    def test_failed_digest_is_retried_next_day(self):
        with mock.patch("django.utils.timezone.now", return_value=self.at(5, 9)):
            digest.dispatch(self.at(5, 9))
        AIDigest.objects.update(status=AIDigest.Status.FAILED)
        self.assertEqual(digest.dispatch(self.at(5, 15)), 0)
        self.assertEqual(digest.dispatch(self.at(6, 9)), 1)

    def test_disabled_option_gets_no_digest(self):
        self.org.ai_enabled = False
        self.org.save(update_fields=["ai_enabled"])
        self.assertEqual(digest.dispatch(self.at(5, 9)), 0)


@override_settings(**OPENAI)
class DigestSettingsTests(AIFixtures):
    def test_owner_sets_day_and_hour_in_org_settings(self):
        data = self.client_api.get("/api/v1/organization/settings/").data
        self.assertEqual((data["digest_weekday"], data["digest_hour"]), (0, 9))
        payload = {k: v for k, v in data.items() if k != "timezones" and v is not None}
        payload.update(digest_weekday=4, digest_hour=18)
        response = self.client_api.put("/api/v1/organization/settings/", payload, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.org.refresh_from_db()
        self.assertEqual(
            (self.org.settings["digest_weekday"], self.org.settings["digest_hour"]), (4, 18)
        )


class GroupPromotionBlockTests(AIFixtures):
    ROW = {
        "candidate_key": "g1",
        "group": "Растяжка 5–10",
        "branch": "Орбита",
        "direction": "Растяжка",
        "case": "underfilled",
        "systemic": False,
        "season": {},
        "title": "Наберите детей в растяжку",
        "rationale": "Мест много, спрос есть",
        "action": "Пост про пробное в Instagram",
        "basis": {"available_places": 13, "occupancy_percent": 13, "conversion_percent": 20.0},
    }

    def test_block_becomes_digest_advice_with_numbers(self):
        block = ("group_promotion", "Какие группы продвигать", {"recommendations": [self.ROW]})
        content = digest.compose(self.org, [block], snapshot(), None)
        item = content["highlights"][0]
        self.assertEqual(item["title"], "Наберите детей в растяжку")
        self.assertEqual(
            [(e["label"], e["value"]) for e in item["evidence"]],
            [
                ("Растяжка 5–10, Орбита: свободных мест", 13),
                ("Растяжка 5–10, Орбита: заполняемость, %", 13),
                ("Растяжка 5–10, Орбита: конверсия заявок направления, %", 20.0),
            ],
        )

    def test_same_group_next_week_is_the_same_advice(self):
        block = [("group_promotion", "", {"recommendations": [self.ROW]})]
        first = digest.compose(self.org, block, snapshot(), None)
        previous = AIDigest(
            organization=self.org, week_start=datetime.date(2026, 9, 28), content=first
        )
        reworded = {**self.ROW, "title": "Растяжке нужны дети"}
        second = digest.compose(
            self.org,
            [("group_promotion", "", {"recommendations": [reworded]})],
            snapshot(),
            previous,
        )
        self.assertTrue(second["changes"]["unchanged"])
