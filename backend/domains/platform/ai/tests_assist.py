"""Вторая волна ИИ: напоминания, заметка о звонке, «перед звонком», подбор
группы, план дня, причина отказа. Модель подменена — проверяем то, что
считает код, и что уходит в модель (телефоны — нет)."""

import datetime

from rest_framework.test import APIClient

from domains.money.subscriptions.sales import sell_subscription
from domains.money.subscriptions.subscription_types import create_type
from domains.people.clients.models import (
    Child,
    ChildContact,
    CommunicationLog,
    ContactPhone,
    ParentContact,
)
from domains.platform.leads.models import LeadRejectionReason
from domains.platform.leads.services import create_lead
from domains.platform.tenants.models import Branch
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group, GroupMembership

from .assist import _first_name
from .tests import AIFixtures, fake_response, patched_client


class AssistFixtures(AIFixtures):
    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.create(organization=self.org, name="Центр")
        self.child = Child.objects.create(
            organization=self.org,
            full_name="Сейтова Алия",
            birth_date=datetime.date(2019, 3, 1),
            gender="female",
        )
        self.parent = ParentContact.objects.create(
            organization=self.org, full_name="Сейтова Айгерим"
        )
        ContactPhone.objects.create(
            organization=self.org, parent_contact=self.parent, number="+77071112233"
        )
        ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=self.parent,
            role="mother",
            is_payer=True,
        )
        version = create_type(
            self.org,
            name="8 занятий",
            price=25000,
            quota_sessions=8,
            duration_days=30,
            directions=[self.ballet],
        ).versions.latest()
        sell_subscription(
            actor=self.owner,
            child=self.child,
            subscription_type_version=version,
            direction=self.ballet,
            branch=self.branch,
            starts_on=datetime.date.today(),
            paid_amount=10000,
            payment_method="cash",
        )

    def call(self, url, payload, answer, client=None):
        patch, create = patched_client(fake_response(answer))
        with patch:
            response = (client or self.client_api).post(url, payload, format="json")
        prompt = create.call_args.kwargs["messages"][0]["content"] if create.called else ""
        return response, prompt


class FirstNameTests(AssistFixtures):
    def test_first_name(self):
        self.assertEqual(_first_name("Сейтова Айгерим"), "Айгерим")
        self.assertEqual(_first_name("Айгерим Сейтова"), "Айгерим")
        self.assertEqual(_first_name("Динара"), "Динара")


class RemindersTests(AssistFixtures):
    def test_debt_reminders_with_payer_phone_not_sent_to_model(self):
        answer = {
            "messages": [
                {"number": 1, "text": "Айгерим, здравствуйте! Напоминаем об оплате 15 000 ₸."}
            ]
        }
        response, prompt = self.call(
            "/api/v1/ai/reminders/",
            {"children": [str(self.child.id)], "kind": "debt", "language": "ru"},
            answer,
        )
        self.assertEqual(response.status_code, 200, response.data)
        item = response.data["items"][0]
        self.assertEqual((item["phone"], item["parent_name"]), ("+77071112233", "Сейтова Айгерим"))
        self.assertIn("15 000", item["text"])
        self.assertIn('"долг": "15 000 ₸"', prompt)
        self.assertIn('"родитель": "Айгерим"', prompt)
        self.assertNotIn("7071112233", prompt)

    def test_teacher_forbidden_and_bad_kind(self):
        teacher = User.objects.create_user(
            phone="77010000061", password="p", full_name="T", organization=self.org, role="teacher"
        )
        client = APIClient()
        client.force_authenticate(user=teacher)
        self.assertEqual(
            client.post(
                "/api/v1/ai/reminders/", {"children": [], "kind": "debt"}, format="json"
            ).status_code,
            403,
        )
        response, _ = self.call(
            "/api/v1/ai/reminders/", {"children": [str(self.child.id)], "kind": "x"}, {}
        )
        self.assertEqual(response.status_code, 400)


class CommunicationNoteTests(AssistFixtures):
    def test_note(self):
        answer = {
            "channel": "call",
            "note": "Мама оплатит в пятницу.",
            "next_step": "Проверить оплату в пятницу",
        }
        response, prompt = self.call(
            "/api/v1/ai/communication-note/", {"text": "звонила маме оплатит в пятницу"}, answer
        )
        self.assertEqual(response.data, answer)
        self.assertIn("звонила маме", prompt)


class ChildBriefTests(AssistFixtures):
    def test_brief_includes_money_for_admin_and_hides_for_teacher(self):
        CommunicationLog.objects.create(
            organization=self.org,
            child=self.child,
            channel="call",
            note="Болела, вернётся в понедельник",
            author=self.owner,
        )
        answer = {"points": ["Долг 15 000 ₸", "Болела"], "suggestion": "Уточнить, когда вернётся"}
        response, prompt = self.call(f"/api/v1/ai/children/{self.child.id}/brief/", {}, answer)
        self.assertEqual(response.data["points"], ["Долг 15 000 ₸", "Болела"])
        self.assertIn('"долг": "15 000 ₸"', prompt)
        self.assertIn("Болела, вернётся", prompt)
        teacher = User.objects.create_user(
            phone="77010000062", password="p", full_name="T", organization=self.org, role="teacher"
        )
        client = APIClient()
        client.force_authenticate(user=teacher)
        _, prompt = self.call(
            f"/api/v1/ai/children/{self.child.id}/brief/", {}, answer, client=client
        )
        self.assertNotIn("долг", prompt)


class LeadGroupsTests(AssistFixtures):
    def test_candidates_by_age_direction_and_free_places(self):
        fits = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.ballet,
            name="Балет 5–8",
            capacity=10,
            age_min=5,
            age_max=8,
        )
        Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.ballet,
            name="Балет 10–14",
            capacity=10,
            age_min=10,
            age_max=14,
        )
        full = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.ballet,
            name="Полная",
            capacity=1,
            age_min=5,
            age_max=8,
        )
        GroupMembership.objects.create(
            organization=self.org, group=full, child=self.child, joined_at=datetime.date.today()
        )
        lead = create_lead(
            organization=self.org,
            actor=self.owner,
            parent_name="А",
            phone="+77070000001",
            child_age=6,
            direction=self.ballet,
        )
        lead.comments.create(organization=self.org, author=self.owner, text="Удобно по субботам")
        answer = {
            "picks": [
                {"number": 1, "reason": "Подходит по возрасту"},
                {"number": 9, "reason": "нет такой"},
            ]
        }
        response, prompt = self.call(f"/api/v1/ai/leads/{lead.id}/groups/", {}, answer)
        self.assertEqual([p["id"] for p in response.data["picks"]], [str(fits.id)])
        self.assertIn("Удобно по субботам", prompt)
        self.assertNotIn("Балет 10–14", prompt)
        self.assertNotIn("Полная", prompt)

    def test_no_candidates(self):
        lead = create_lead(
            organization=self.org,
            actor=self.owner,
            parent_name="А",
            phone="+77070000001",
            child_age=30,
        )
        response, prompt = self.call(f"/api/v1/ai/leads/{lead.id}/groups/", {}, {"picks": []})
        self.assertEqual(response.data["picks"], [])
        self.assertEqual(prompt, "")  # в модель не ходили


class DailyPlanTests(AssistFixtures):
    def test_plan_links_limited_to_known(self):
        create_lead(organization=self.org, actor=self.owner, parent_name="А", phone="+77070000001")
        answer = {"tasks": [{"text": "Позвонить 1 новой заявке", "link": "/leads"}]}
        patch, create = patched_client(fake_response(answer))
        with patch:
            response = self.client_api.post("/api/v1/ai/daily-plan/", {}, format="json")
        self.assertEqual(response.data["tasks"], answer["tasks"])
        schema = create.call_args.kwargs["output_config"]["format"]["schema"]
        links = schema["properties"]["tasks"]["items"]["properties"]["link"]["enum"]
        self.assertIn("/leads", links)
        self.assertIn("/attendance", links)


class RejectionReasonTests(AssistFixtures):
    def test_reason_from_comment(self):
        far = LeadRejectionReason.objects.get(organization=self.org, name="Далеко", kind="new")
        response, prompt = self.call(
            "/api/v1/ai/rejection-reason/",
            {"text": "переехали на левый берег, ездить неудобно"},
            {"reason": "Далеко"},
        )
        self.assertEqual(response.data, {"reason": str(far.id), "name": "Далеко"})
        self.assertIn("левый берег", prompt)
