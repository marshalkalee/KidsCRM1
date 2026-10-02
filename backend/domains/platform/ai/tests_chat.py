"""Чат с ИИ на главной (ai/chat.py): модель подменена — проверяем, кому
чат доступен, что инструменты смотрят данные с правами спрашивающего,
что контакты не уходят в модель и как устроен цикл вызовов у обоих
провайдеров, как переписка сохраняется и кто её видит."""

import json
from datetime import date
from types import SimpleNamespace
from unittest import mock

from django.test import override_settings, tag
from rest_framework.test import APIClient

from domains.people.clients.models import Child, ChildContact, ContactPhone, ParentContact
from domains.platform.tenants.models import Branch, Organization
from domains.platform.users.models import User

from . import chat, services
from .models import AIConversation, AIMessage
from .tests import AIFixtures


def api_as(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def ask_as(user, message, conversation=None):
    body = {"message": message, **({"conversation": conversation} if conversation else {})}
    return api_as(user).post("/api/v1/ai/chat/", body, format="json")


def anthropic_answers(*texts):
    create = mock.Mock(side_effect=[final_text(t) for t in texts])
    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    return mock.patch.object(services, "_client", return_value=client), create


class ChatFixtures(AIFixtures):
    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.create(organization=self.org, name="Алмалы")
        self.child = Child.objects.create(
            organization=self.org, full_name="Касымова Айлин", birth_date=date(2017, 6, 13)
        )
        self.parent = ParentContact.objects.create(
            organization=self.org,
            full_name="Касымова Гульмира",
            whatsapp="+77015554433",
            email="mama@example.kz",
        )
        ContactPhone.objects.create(parent_contact=self.parent, number="+77015554433")
        ChildContact.objects.create(
            organization=self.org, child=self.child, parent_contact=self.parent, is_payer=True
        )
        self.viewer = chat.Viewer(self.owner)

    def user(self, role, phone):
        return User.objects.create_user(
            phone=phone, password="x", full_name=role, organization=self.org, role=role
        )


class ChatAccessTests(ChatFixtures):
    def test_only_leaders_and_admin(self):
        for role, phone in (("teacher", "77010000002"), ("accountant", "77010000003")):
            with self.subTest(role=role):
                self.assertEqual(ask_as(self.user(role, phone), "Привет").status_code, 403)
        me = self.client_api.get("/api/v1/users/auth/me/").data
        self.assertTrue(me["permissions"]["can_use_ai_chat"])

    def test_disabled_without_key(self):
        with override_settings(ANTHROPIC_API_KEY=""):
            response = ask_as(self.owner, "Привет")
        self.assertEqual(response.status_code, 400)
        self.assertIn("не настроен", response.data["detail"])

    def test_empty_question(self):
        response = ask_as(self.owner, "   ")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Напишите вопрос", response.data["detail"])


class ChatHistoryTests(ChatFixtures):
    def test_conversation_is_saved_and_continued(self):
        patch, create = anthropic_answers("Долгов нет.", "Да, все оплатили.")
        with patch:
            first = ask_as(self.owner, "Есть долги?")
            conversation = first.data["conversation"]["id"]
            second = ask_as(self.owner, "Точно?", conversation)
        self.assertEqual(first.data["conversation"]["title"], "Есть долги?")
        self.assertEqual(second.data["conversation"]["id"], conversation)
        # Во второй вопрос модель получила всю переписку этого чата.
        roles = [(m["role"], m["content"]) for m in create.call_args_list[1].kwargs["messages"]]
        self.assertEqual(
            roles,
            [("user", "Есть долги?"), ("assistant", "Долгов нет."), ("user", "Точно?")],
        )
        listed = api_as(self.owner).get("/api/v1/ai/conversations/").data
        self.assertEqual([c["id"] for c in listed], [conversation])
        detail = api_as(self.owner).get(f"/api/v1/ai/conversations/{conversation}/").data
        self.assertEqual(
            [m["content"] for m in detail["messages"]],
            ["Есть долги?", "Долгов нет.", "Точно?", "Да, все оплатили."],
        )

    def test_failed_answer_saves_nothing(self):
        with override_settings(ANTHROPIC_API_KEY=""):
            ask_as(self.owner, "Есть долги?")
        self.assertEqual(api_as(self.owner).get("/api/v1/ai/conversations/").data, [])

    def test_only_author_sees_conversation(self):
        patch, _ = anthropic_answers("Ответ.")
        with patch:
            conversation = ask_as(self.owner, "Мой вопрос").data["conversation"]["id"]
        manager = self.user("manager", "77010000005")
        self.assertEqual(api_as(manager).get("/api/v1/ai/conversations/").data, [])
        url = f"/api/v1/ai/conversations/{conversation}/"
        self.assertEqual(api_as(manager).get(url).status_code, 404)
        self.assertEqual(api_as(manager).delete(url).status_code, 404)
        self.assertEqual(ask_as(manager, "Влезть", conversation).status_code, 404)

    def test_delete(self):
        patch, _ = anthropic_answers("Ответ.")
        with patch:
            conversation = ask_as(self.owner, "Вопрос").data["conversation"]["id"]
        url = f"/api/v1/ai/conversations/{conversation}/"
        self.assertEqual(api_as(self.owner).delete(url).status_code, 204)
        self.assertEqual(api_as(self.owner).get("/api/v1/ai/conversations/").data, [])
        self.assertEqual(api_as(self.owner).get(url).status_code, 404)

    def test_long_question_title_is_cut(self):
        self.assertEqual(len(chat._title("слово " * 50)), chat.TITLE_CHARS)


class ChatToolsTests(ChatFixtures):
    def test_contacts_never_reach_the_model(self):
        for name, args in (
            ("child_card", {"child_id": str(self.child.id)}),
            ("parent_card", {"parent_id": str(self.parent.id)}),
            ("search", {"q": "Касымова"}),
        ):
            with self.subTest(tool=name):
                out = chat.run_tool(self.viewer, name, args)
                self.assertIn("Касымова", out)
                self.assertNotIn("5554433", out)
                self.assertNotIn("example.kz", out)

    def test_same_permissions_as_screens(self):
        admin = chat.Viewer(self.user("admin", "77010000004"))
        out = json.loads(chat.run_tool(admin, "metrics", {"metrics": "revenue"}))
        self.assertIn("нет доступа", out["ошибка"])
        owner_out = json.loads(chat.run_tool(self.viewer, "metrics", {"metrics": "revenue"}))
        self.assertIn("revenue", owner_out["metrics"])

    @tag("tenant_isolation")
    def test_foreign_child_is_not_found(self):
        other = Organization.objects.create(name="Чужой центр", slug="other")
        foreign = Child.objects.create(
            organization=other, full_name="Чужой Ребёнок", birth_date=date(2018, 1, 1)
        )
        out = json.loads(chat.run_tool(self.viewer, "child_card", {"child_id": str(foreign.id)}))
        self.assertEqual(out, {"ошибка": "не найдено"})
        children = chat.run_tool(self.viewer, "children", {"q": "Чужой"})
        self.assertNotIn("Чужой Ребёнок", children)

    def test_branch_name_becomes_id(self):
        out = json.loads(chat.run_tool(self.viewer, "groups", {"branch": "алмалы"}))
        self.assertEqual(out["count"], 0)
        out = json.loads(chat.run_tool(self.viewer, "groups", {"branch": "Нет такого"}))
        self.assertIn("не найден однозначно", out["ошибка"])

    def test_bad_id_is_explained(self):
        out = json.loads(chat.run_tool(self.viewer, "child_card", {"child_id": "Айлин"}))
        self.assertIn("UUID", out["ошибка"])

    def test_shrink_drops_noise_and_cuts_long_lists(self):
        data = {
            "organization": "x",
            "branch": "id",
            "branch_name": "Алмалы",
            "child_id": "c1",
            "child_name": "Айлин",
            "note": "",
            "rows": list(range(chat.MAX_LIST_ITEMS + 5)),
        }
        out = chat._shrink(data)
        self.assertEqual(set(out), {"branch_name", "child_id", "child_name", "rows"})
        self.assertEqual(len(out["rows"]), chat.MAX_LIST_ITEMS + 1)


def tool_use(name, args, block_id="tu_1"):
    return SimpleNamespace(
        stop_reason="tool_use",
        content=[SimpleNamespace(type="tool_use", id=block_id, name=name, input=args)],
    )


def final_text(text):
    return SimpleNamespace(
        stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)]
    )


class ChatAnthropicLoopTests(ChatFixtures):
    def test_tool_result_goes_back_and_answer_returns(self):
        create = mock.Mock(
            side_effect=[
                tool_use("search", {"q": "Касымова"}),
                final_text("Нашла: Касымова Айлин."),
            ]
        )
        client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
        with mock.patch.object(services, "_client", return_value=client):
            response = ask_as(self.owner, "Найди Касымову")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["answer"], "Нашла: Касымова Айлин.")
        self.assertEqual(response.data["sources"], ["поиск"])
        second = create.call_args_list[1].kwargs
        self.assertIn("True Ballet", second["system"])
        result = second["messages"][-1]["content"][0]
        self.assertEqual((result["type"], result["tool_use_id"]), ("tool_result", "tu_1"))
        self.assertIn("Касымова Айлин", result["content"])
        self.assertEqual({t["name"] for t in second["tools"]}, set(chat.TOOLS_BY_NAME))

    def test_endless_tool_calls_stop(self):
        create = mock.Mock(return_value=tool_use("branches", {}))
        client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
        with mock.patch.object(services, "_client", return_value=client):
            response = ask_as(self.owner, "?")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(create.call_count, chat.MAX_TOOL_ROUNDS)


def openai_message(content=None, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls, refusal=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])


def openai_call(name, args, call_id="call_1"):
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=json.dumps(args, ensure_ascii=False)),
    )


@override_settings(
    AI_PROVIDER="openai",
    OPENAI_API_KEY="sk-test",
    OPENAI_MODEL="gpt-test",
    OPENAI_CHAT_MODEL="gpt-chat-test",
    ANTHROPIC_API_KEY="",
)
class ChatOpenAILoopTests(ChatFixtures):
    def test_tool_call_then_answer(self):
        create = mock.Mock(
            side_effect=[
                openai_message(
                    tool_calls=[openai_call("child_card", {"child_id": str(self.child.id)})]
                ),
                openai_message(content="У Айлин долга нет."),
            ]
        )
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        conversation = AIConversation.objects.create(
            organization=self.org, user=self.owner, title="Привет"
        )
        AIMessage.objects.create(conversation=conversation, role="user", content="Привет")
        AIMessage.objects.create(
            conversation=conversation, role="assistant", content="Здравствуйте!"
        )
        with mock.patch.object(services, "_openai_client", return_value=client):
            response = ask_as(self.owner, "Что с Айлин?", str(conversation.id))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["answer"], "У Айлин долга нет.")
        self.assertEqual(response.data["sources"], ["карточка ребёнка"])
        second = create.call_args_list[1].kwargs
        self.assertEqual(second["model"], "gpt-chat-test")
        self.assertEqual(second["messages"][0]["role"], "system")
        self.assertEqual(
            [m["role"] for m in second["messages"][1:4]], ["user", "assistant", "user"]
        )
        tool_message = second["messages"][-1]
        self.assertEqual((tool_message["role"], tool_message["tool_call_id"]), ("tool", "call_1"))
        self.assertIn("Касымова Айлин", tool_message["content"])
        self.assertNotIn("5554433", tool_message["content"])
