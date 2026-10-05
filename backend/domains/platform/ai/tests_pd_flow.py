"""TRU-156: какие персональные данные фактически уходят во внешнюю модель.

Модель подменена записывающей заглушкой. Каждая ИИ-функция вызывается на
данных с метками; найденные в запросе метки сверяются с описью
pd_inventory.INVENTORY. Новая функция, не внесённая в опись, роняет тест.
"""

import datetime
import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import get_resolver
from django.utils import timezone
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
from domains.platform.leads.services import create_lead
from domains.platform.tenants.models import Branch
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.schedule.models import Lesson

from . import chat, pd_inventory
from .pd_inventory import (
    BIRTH_DATE,
    CHILD_NAME,
    EMAIL,
    MEDICAL,
    PARENT_NAME,
    PHONE,
    STAFF_NAME,
)
from .tests import AIFixtures, fake_response, patched_client

# Метка → категория. Метки не встречаются нигде, кроме своих полей.
MARKERS = {
    "Бекова": CHILD_NAME,
    "Алтынай": CHILD_NAME,
    "Тимурлан": CHILD_NAME,
    "Гаухар": PARENT_NAME,
    "Меруерт": PARENT_NAME,
    "2019-03-01": BIRTH_DATE,
    "01.03.2019": BIRTH_DATE,
    "арахис": MEDICAL,
    "Нурланова": PARENT_NAME,
    "Сапарова": PARENT_NAME,
    "7071112233": PHONE,
    "7015554433": PHONE,
    "mama@example.kz": EMAIL,
    "Жумабекова": STAFF_NAME,
}


def found(text) -> set:
    return {category for marker, category in MARKERS.items() if marker in text}


class PDFlowFixtures(AIFixtures):
    def setUp(self):
        super().setUp()
        self.owner.full_name = "Жумабекова Сауле"
        self.owner.save(update_fields=["full_name"])
        self.api = APIClient(raise_request_exception=False)
        self.api.force_authenticate(user=self.owner)
        branch = Branch.objects.create(organization=self.org, name="Центр")
        self.child = Child.objects.create(
            organization=self.org,
            full_name="Бекова Алтынай",
            birth_date=datetime.date(2019, 3, 1),
            gender="female",
            medical_notes="Аллергия на арахис",
        )
        self.parent = ParentContact.objects.create(
            organization=self.org,
            full_name="Нурланова Гаухар",
            whatsapp="+77071112233",
            email="mama@example.kz",
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
        CommunicationLog.objects.create(
            organization=self.org,
            child=self.child,
            author=self.owner,
            note="Мама просила перезвонить вечером",
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
            branch=branch,
            starts_on=datetime.date.today(),
            paid_amount=10000,
            payment_method="cash",
        )
        self.group = Group.objects.create(
            organization=self.org,
            branch=branch,
            direction=self.ballet,
            name="Балет 5–7",
            capacity=12,
        )
        GroupMembership.objects.create(
            organization=self.org,
            group=self.group,
            child=self.child,
            joined_at=datetime.date.today(),
        )
        start = timezone.now()
        self.lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            teacher=self.owner,
            starts_at=start,
            ends_at=start + datetime.timedelta(hours=1),
        )
        self.lead = create_lead(
            organization=self.org,
            actor=self.owner,
            parent_name="Сапарова Меруерт",
            phone="+77015554433",
            child_name="Тимурлан",
            child_age=6,
            direction=self.ballet,
            branch=branch,
        )

    def sent(self, call) -> set:
        """Категории в том, что функция отправила в модель."""
        patch, create = patched_client(fake_response({}))
        with patch:
            call()
        return found(
            json.dumps([c.kwargs for c in create.call_args_list], ensure_ascii=False, default=str)
        )


class PDFlowTests(PDFlowFixtures):
    maxDiff = None

    def functions(self):
        api = self.api
        neutral = "Позвонила, договорились о пробном на субботу"
        return {
            "lead_from_text": lambda: api.post(
                "/api/v1/ai/lead-from-text/",
                {"text": "Сапарова Меруерт, 87015554433, сыну 6 лет"},
                format="json",
            ),
            "lead_message": lambda: api.post(
                f"/api/v1/ai/leads/{self.lead.id}/message/",
                {"goal": "first_contact", "language": "ru"},
                format="json",
            ),
            "search": lambda: api.post(
                "/api/v1/ai/search/", {"query": "дети с долгом"}, format="json"
            ),
            "attendance_photo": lambda: api.post(
                "/api/v1/ai/attendance-photo/",
                {
                    "lesson": str(self.lesson.id),
                    "image": SimpleUploadedFile("j.jpg", b"\xff\xd8x", content_type="image/jpeg"),
                },
            ),
            "import_clean": lambda: api.post(
                "/api/v1/ai/import-clean/",
                {
                    "file": SimpleUploadedFile(
                        "kids.csv",
                        "Ученик;Мама\nСапарова Тимурлан;87015554433\n".encode(),
                        content_type="text/csv",
                    )
                },
            ),
            "reminders": lambda: api.post(
                "/api/v1/ai/reminders/",
                {"children": [str(self.child.id)], "kind": "debt", "language": "ru"},
                format="json",
            ),
            "communication_note": lambda: api.post(
                "/api/v1/ai/communication-note/", {"text": neutral}, format="json"
            ),
            "child_brief": lambda: api.post(f"/api/v1/ai/children/{self.child.id}/brief/"),
            "lead_groups": lambda: api.post(f"/api/v1/ai/leads/{self.lead.id}/groups/"),
            "daily_plan": lambda: api.post("/api/v1/ai/daily-plan/"),
            "rejection_reason": lambda: api.post(
                "/api/v1/ai/rejection-reason/", {"text": "дорого"}, format="json"
            ),
            "chat": lambda: api.post("/api/v1/ai/chat/", {"message": "Что нового?"}, format="json"),
        }

    def tool_args(self):
        ids = {
            "child_id": str(self.child.id),
            "parent_id": str(self.parent.id),
            "group_id": str(self.group.id),
            "lead_id": str(self.lead.id),
            "q": "Бекова",
            "metrics": "revenue",
            "metric": "revenue",
            "by": "branch",
            "date_from": datetime.date.today().isoformat(),
            "date_to": datetime.date.today().isoformat(),
        }
        return {
            tool["name"]: {k: ids[k] for k in tool["parameters"]["required"]} for tool in chat.TOOLS
        }

    def actual(self) -> dict:
        result = {name: self.sent(call) for name, call in self.functions().items()}
        viewer = chat.Viewer(self.owner)
        for name, args in self.tool_args().items():
            result[f"chat:{name}"] = found(chat.run_tool(viewer, name, args))
        return result

    def test_inventory_matches_what_reaches_the_model(self):
        expected = {
            name: set(info["sends"]) - {pd_inventory.INPUT}
            for name, info in pd_inventory.INVENTORY.items()
        }
        actual = self.actual()
        self.assertEqual(
            {k: sorted(v) for k, v in actual.items()},
            {k: sorted(v) for k, v in expected.items() if k in actual},
            "Изменилось, что уходит в модель: обновите pd_inventory.INVENTORY и "
            "проверьте по docs/adr/0008-ai-boundaries.md.",
        )

    def test_every_ai_endpoint_is_in_inventory(self):
        """Новый ИИ-эндпоинт без записи в описи — сборка падает."""
        routes = {pattern.name for pattern in get_resolver("domains.platform.ai.urls").url_patterns}
        described = {info["route"] for info in pd_inventory.INVENTORY.values() if "route" in info}
        service_routes = {"status", "conversations", "conversation-detail"}
        self.assertEqual(routes - service_routes, described)

    def test_medical_notes_never_leave(self):
        """Данные о здоровье ребёнка — ни одной функцией, ни одним инструментом."""
        for name, categories in self.actual().items():
            with self.subTest(function=name):
                self.assertNotIn(MEDICAL, categories)

    def test_phones_and_email_never_leave_from_crm_data(self):
        """Контакты из базы не уходят ни одной функцией — только если сотрудник
        сам вставил их в текст или файл (INPUT)."""
        for name, categories in self.actual().items():
            input_driven = pd_inventory.INPUT in pd_inventory.INVENTORY.get(name, {}).get(
                "sends", ()
            )
            if input_driven:
                continue
            with self.subTest(function=name):
                self.assertFalse({PHONE, EMAIL} & categories, categories)
