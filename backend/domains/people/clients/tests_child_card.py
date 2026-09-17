"""
Карточка ребёнка: каркас и вкладки (ТЗ п. 4.1). Критерии приёмки:
- каркас с пятью вкладками, две наполнены (Контакты, Коммуникации), три
  показывают заглушку (Абонементы, Оплаты, Посещения);
- интерфейс подключения вкладки описан в child_card_tabs.py — здесь
  проверяем сам контракт (сколько вкладок, у скольких есть url_name);
- запись в «Коммуникациях» создаётся минимальным набором полей (канал +
  заметка, без обязательного выбора конкретного контакта) — "за пару
  кликов";
- редактирование основных полей повторяет правила Child.ALLOWED_STATUS_TRANSITIONS
  (та же проверка, что и в API, не отдельная копия правила).
"""

import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from domains.platform.tenants.models import Direction, Organization

from .child_card_tabs import get_child_card_tabs
from .models import Child, ChildContact, CommunicationLog, ParentContact

User = get_user_model()


def _make_child(org, name="Аружан", **extra):
    defaults = {
        "organization": org,
        "full_name": name,
        "birth_date": datetime.date.today() - datetime.timedelta(days=365 * 7),
        "gender": Child.Gender.FEMALE,
    }
    defaults.update(extra)
    return Child.objects.create(**defaults)


class ChildCardTabsContractTests(TestCase):
    def test_five_tabs_two_wired_three_stubs(self):
        tabs = get_child_card_tabs()

        self.assertEqual(len(tabs), 5)
        wired = [tab for tab in tabs if tab.url_name is not None]
        stubs = [tab for tab in tabs if tab.url_name is None]
        self.assertEqual({tab.slug for tab in wired}, {"contacts", "communications"})
        self.assertEqual({tab.slug for tab in stubs}, {"subscriptions", "payments", "attendance"})

    def test_tabs_are_ordered(self):
        tabs = get_child_card_tabs()
        self.assertEqual([tab.order for tab in tabs], sorted(tab.order for tab in tabs))


class ChildCardWebViewTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.branch_direction = Direction.objects.create(organization=self.org, name="Балет")
        self.child = _make_child(self.org)
        self.child.directions.add(self.branch_direction)
        self.owner = User.objects.create_user(
            phone="+77010000001",
            full_name="Owner",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.teacher = User.objects.create_user(
            phone="+77010000002",
            full_name="Teacher",
            password="pass12345",
            organization=self.org,
            role=User.Role.TEACHER,
        )

    def test_card_renders_header_with_age_and_status(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("clients_web:child-card", args=[self.child.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.child.full_name)
        self.assertContains(response, str(self.child.age))

    def test_card_renders_five_tabs(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("clients_web:child-card", args=[self.child.pk]))

        content = response.content.decode()
        for slug in ("contacts", "communications", "subscriptions", "payments", "attendance"):
            self.assertIn(f'data-slug="{slug}"', content)

    def test_stub_tabs_have_no_url(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("clients_web:child-card", args=[self.child.pk]))

        content = response.content.decode()
        # Заглушки — data-url="" (пустая строка), не сломанный маршрут.
        # Атрибуты кнопки на разных строках (так их разложил djlint) —
        # поэтому ищем каждый отдельно, а не одной подстрокой.
        subscriptions_tab = content[content.index('data-slug="subscriptions"') :]
        self.assertIn('data-slug="subscriptions"', subscriptions_tab[:40])
        self.assertIn('data-url=""', subscriptions_tab[:120])

    def test_card_contains_first_tab_content_without_extra_fetch(self):
        ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=ParentContact.objects.create(organization=self.org, full_name="Мама"),
            role=ChildContact.Role.MOTHER,
        )
        self.client.force_login(self.owner)

        response = self.client.get(reverse("clients_web:child-card", args=[self.child.pk]))

        self.assertContains(response, "child-contacts-data")

    def test_teacher_can_open_card_but_not_edit(self):
        self.client.force_login(self.teacher)

        response = self.client.get(reverse("clients_web:child-card", args=[self.child.pk]))

        self.assertEqual(response.status_code, 200)
        # id="js-edit-child" — конкретно сам элемент кнопки; JS-код,
        # который на неё ссылается (getElementById), в разметке есть всегда.
        self.assertNotIn(b'id="js-edit-child"', response.content)


class ChildEditWebViewTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.child = _make_child(self.org)
        self.owner = User.objects.create_user(
            phone="+77010000001",
            full_name="Owner",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.teacher = User.objects.create_user(
            phone="+77010000002",
            full_name="Teacher",
            password="pass12345",
            organization=self.org,
            role=User.Role.TEACHER,
        )

    def _valid_payload(self, **overrides):
        payload = {
            "full_name": self.child.full_name,
            "birth_date": str(self.child.birth_date),
            "gender": self.child.gender,
            "status": self.child.status,
        }
        payload.update(overrides)
        return payload

    def test_owner_edits_main_fields(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("clients_web:child-edit", args=[self.child.pk]),
            self._valid_payload(full_name="Аружан Новая", medical_notes="Аллергия на орехи"),
        )

        self.assertEqual(response.status_code, 302)
        self.child.refresh_from_db()
        self.assertEqual(self.child.full_name, "Аружан Новая")
        self.assertEqual(self.child.medical_notes, "Аллергия на орехи")

    def test_transition_to_left_without_reason_is_rejected(self):
        # AJAX-заголовок — так реально уходит форма из модалки (form-modal.js);
        # без него, как и у всех форм в проекте, невалидный POST рендерит
        # полную страницу со статусом 200 (см. tests_web_views.py — тот же
        # принцип у ChildContactForm).
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("clients_web:child-edit", args=[self.child.pk]),
            self._valid_payload(status="left"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        self.child.refresh_from_db()
        self.assertEqual(self.child.status, Child.Status.ACTIVE)

    def test_disallowed_status_transition_is_rejected(self):
        self.child.status = Child.Status.LEFT
        self.child.leave_reason = "Переезд"
        self.child.save(update_fields=["status", "leave_reason"])
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("clients_web:child-edit", args=[self.child.pk]),
            self._valid_payload(status="paused", leave_reason="Переезд"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)

    def test_teacher_cannot_edit(self):
        self.client.force_login(self.teacher)

        response = self.client.get(reverse("clients_web:child-edit", args=[self.child.pk]))

        self.assertEqual(response.status_code, 403)


class CommunicationLogTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.child = _make_child(self.org)
        self.mother = ParentContact.objects.create(organization=self.org, full_name="Мама")
        self.owner = User.objects.create_user(
            phone="+77010000001",
            full_name="Owner",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.teacher = User.objects.create_user(
            phone="+77010000002",
            full_name="Teacher",
            password="pass12345",
            organization=self.org,
            role=User.Role.TEACHER,
        )

    def test_minimal_payload_creates_entry_in_one_request(self):
        """ "За пару кликов": канал + заметка — этого достаточно, без выбора
        конкретного контакта."""
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("clients_web:child-communication-create", args=[self.child.pk]),
            {"channel": "call", "note": "Обсудили расписание на неделю"},
        )

        self.assertEqual(response.status_code, 200)
        log = CommunicationLog.objects.get(child=self.child)
        self.assertEqual(log.channel, CommunicationLog.Channel.CALL)
        self.assertEqual(log.author, self.owner)
        self.assertIsNone(log.parent_contact)

    def test_entry_with_parent_contact(self):
        # Форма предлагает только контакты, уже привязанные к этому
        # ребёнку (см. CommunicationLogForm.__init__) — иначе можно было бы
        # отметить звонок с произвольным родителем, не имеющим к ребёнку
        # никакого отношения.
        ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=self.mother,
            role=ChildContact.Role.MOTHER,
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("clients_web:child-communication-create", args=[self.child.pk]),
            {
                "channel": "whatsapp",
                "note": "Прислали справку",
                "parent_contact": str(self.mother.pk),
            },
        )

        self.assertEqual(response.status_code, 200)
        log = CommunicationLog.objects.get(child=self.child)
        self.assertEqual(log.parent_contact, self.mother)

    def test_note_is_required(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("clients_web:child-communication-create", args=[self.child.pk]),
            {"channel": "call", "note": ""},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(CommunicationLog.objects.filter(child=self.child).exists())

    def test_teacher_cannot_add_entry(self):
        self.client.force_login(self.teacher)

        response = self.client.post(
            reverse("clients_web:child-communication-create", args=[self.child.pk]),
            {"channel": "call", "note": "Test"},
        )

        self.assertEqual(response.status_code, 403)

    def test_teacher_can_view_communications_tab(self):
        CommunicationLog.objects.create(
            organization=self.org, child=self.child, channel="call", note="Test", author=self.owner
        )
        self.client.force_login(self.teacher)

        response = self.client.get(
            reverse("clients_web:child-tab-communications", args=[self.child.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test")
        # У преподавателя нет прав добавлять запись — формы в фрагменте нет.
        self.assertNotIn(b"js-communication-form", response.content)

    def test_log_entries_ordered_newest_first(self):
        first = CommunicationLog.objects.create(
            organization=self.org,
            child=self.child,
            channel="call",
            note="Первый",
            author=self.owner,
        )
        second = CommunicationLog.objects.create(
            organization=self.org,
            child=self.child,
            channel="comment",
            note="Второй",
            author=self.owner,
        )

        logs = list(CommunicationLog.objects.filter(child=self.child))

        self.assertEqual(logs, [second, first])

    def test_deleting_parent_contact_keeps_log_with_null_reference(self):
        log = CommunicationLog.objects.create(
            organization=self.org,
            child=self.child,
            channel="call",
            note="Test",
            author=self.owner,
            parent_contact=self.mother,
        )

        self.mother.hard_delete()

        log.refresh_from_db()
        self.assertIsNone(log.parent_contact)
