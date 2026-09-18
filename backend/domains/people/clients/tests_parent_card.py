"""
Карточка родителя: дети, контакты, сводная задолженность (ТЗ п. 4.1, п. 4.5).
Критерии приёмки:
- родитель с детьми в двух разных филиалах виден полностью в одной карточке;
- кнопка WhatsApp — deep-link wa.me с уже подставленным номером;
- сводная задолженность/история оплат — на этом тикете модуль оплат
  (domains/money) ещё пустая заглушка (см. models.py там), поэтому карточка
  показывает плейсхолдер "появится", а не считает сумму сама — иначе на
  приёмке (сверка с экраном Bekzat'а) цифры разошлись бы между экранами.
"""

import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from domains.platform.tenants.models import Branch, Direction, Organization

from .models import Child, ChildContact, CommunicationLog, ContactPhone, ParentContact

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


class ParentCardWebViewTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.parent = ParentContact.objects.create(
            organization=self.org, full_name="Мама Тестова", whatsapp="+77011234567", email="a@b.kz"
        )
        self.phone = ContactPhone.objects.create(
            organization=self.org, parent_contact=self.parent, number="+77011234567"
        )
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

    def test_card_renders_name_and_email(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("clients_web:parent-card", args=[self.parent.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Мама Тестова")
        self.assertContains(response, "a@b.kz")

    def test_call_url_uses_first_phone(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("clients_web:parent-card", args=[self.parent.pk]))

        self.assertContains(response, f"tel:{self.phone.number}")

    def test_whatsapp_url_strips_plus_for_deep_link(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("clients_web:parent-card", args=[self.parent.pk]))

        self.assertContains(response, "https://wa.me/77011234567")

    def test_teacher_does_not_see_phone_or_whatsapp(self):
        self.client.force_login(self.teacher)

        response = self.client.get(reverse("clients_web:parent-card", args=[self.parent.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.phone.number)
        self.assertNotContains(response, "wa.me")

    def test_teacher_sees_no_edit_or_log_communication_button(self):
        self.client.force_login(self.teacher)

        response = self.client.get(reverse("clients_web:parent-card", args=[self.parent.pk]))

        self.assertNotIn(b'id="js-edit-parent"', response.content)
        self.assertNotIn(b'id="js-log-communication"', response.content)

    def test_children_in_two_different_branches_both_appear_on_one_card(self):
        # Критерий приёмки: родитель с детьми в двух разных филиалах виден
        # полностью в одной карточке — не переключаясь между двумя
        # карточками детей, чтобы сложить долг.
        branch_a = Branch.objects.create(organization=self.org, name="Филиал А")
        branch_b = Branch.objects.create(organization=self.org, name="Филиал Б")
        direction_a = Direction.objects.create(organization=self.org, name="Балет")
        direction_a.branches.add(branch_a)
        direction_b = Direction.objects.create(organization=self.org, name="Дзюдо")
        direction_b.branches.add(branch_b)

        child_a = _make_child(self.org, name="Айгерим")
        child_a.directions.add(direction_a)
        child_b = _make_child(self.org, name="Бекзат")
        child_b.directions.add(direction_b)

        ChildContact.objects.create(
            organization=self.org,
            child=child_a,
            parent_contact=self.parent,
            role=ChildContact.Role.MOTHER,
        )
        ChildContact.objects.create(
            organization=self.org,
            child=child_b,
            parent_contact=self.parent,
            role=ChildContact.Role.MOTHER,
        )
        self.client.force_login(self.owner)

        response = self.client.get(reverse("clients_web:parent-card", args=[self.parent.pk]))

        content = response.content.decode()
        self.assertIn(str(child_a.id), content)
        self.assertIn(str(child_b.id), content)
        self.assertIn("Филиал А", content)
        self.assertIn("Филиал Б", content)

    def test_debt_and_payments_show_placeholder_not_a_computed_number(self):
        # Модуль оплат (domains/money) пока пустая заглушка — карточка не
        # должна считать сумму сама, только показывать, что раздел появится.
        self.client.force_login(self.owner)

        response = self.client.get(reverse("clients_web:parent-card", args=[self.parent.pk]))

        self.assertContains(response, "parent_card.debt_placeholder")

    def test_communications_feed_aggregates_across_all_children(self):
        # Тот же принцип, что у критерия "два филиала на одной карточке" —
        # лента коммуникаций тоже должна быть сводной по всем детям
        # родителя, а не только по одному.
        child_a = _make_child(self.org, name="Айгерим")
        child_b = _make_child(self.org, name="Бекзат")
        ChildContact.objects.create(
            organization=self.org,
            child=child_a,
            parent_contact=self.parent,
            role=ChildContact.Role.MOTHER,
        )
        ChildContact.objects.create(
            organization=self.org,
            child=child_b,
            parent_contact=self.parent,
            role=ChildContact.Role.MOTHER,
        )
        log_a = CommunicationLog.objects.create(
            organization=self.org,
            child=child_a,
            channel="call",
            note="Про Айгерим",
            author=self.owner,
        )
        log_b = CommunicationLog.objects.create(
            organization=self.org,
            child=child_b,
            channel="whatsapp",
            note="Про Бекзата",
            author=self.owner,
        )
        self.client.force_login(self.owner)

        response = self.client.get(reverse("clients_web:parent-card", args=[self.parent.pk]))

        # Лента рендерится на клиенте из json_script (кириллица там
        # экранирована в \uXXXX) — как и у списков детей/родителей,
        # проверяем по id, а не по литеральному тексту заметки.
        self.assertContains(response, str(log_a.id))
        self.assertContains(response, str(log_b.id))

    def test_communications_feed_excludes_unrelated_childs_entries(self):
        unrelated_child = _make_child(self.org, name="Чужой")
        other_log = CommunicationLog.objects.create(
            organization=self.org,
            child=unrelated_child,
            channel="call",
            note="Не имеет отношения к этому родителю",
            author=self.owner,
        )
        self.client.force_login(self.owner)

        response = self.client.get(reverse("clients_web:parent-card", args=[self.parent.pk]))

        self.assertNotContains(response, str(other_log.id))

    def test_communications_feed_includes_entries_logged_without_parent_contact_tag(self):
        # CommunicationLog.parent_contact необязателен (см. docstring
        # модели) — лента родителя фильтрует по ребёнку, не по этому полю,
        # значит запись без явно отмеченного контакта всё равно должна
        # попасть в сводную ленту, если ребёнок — один из детей родителя.
        child = _make_child(self.org, name="Дана")
        ChildContact.objects.create(
            organization=self.org,
            child=child,
            parent_contact=self.parent,
            role=ChildContact.Role.MOTHER,
        )
        log = CommunicationLog.objects.create(
            organization=self.org,
            child=child,
            channel="comment",
            note="Заметка без привязки к контакту",
            author=self.owner,
        )
        self.client.force_login(self.owner)

        response = self.client.get(reverse("clients_web:parent-card", args=[self.parent.pk]))

        self.assertContains(response, str(log.id))

    def test_all_communications_are_sent_even_beyond_the_default_collapsed_count(self):
        # "Показать старые записи" — чисто клиентское схлопывание (JS,
        # parent_card.html): сервер должен отдавать ВСЕ записи, а не
        # только последние 5, иначе фильтру по датам/кнопке "показать
        # старые" не из чего будет разворачивать список.
        child = _make_child(self.org, name="Дана")
        ChildContact.objects.create(
            organization=self.org,
            child=child,
            parent_contact=self.parent,
            role=ChildContact.Role.MOTHER,
        )
        logs = [
            CommunicationLog.objects.create(
                organization=self.org,
                child=child,
                channel="call",
                note=f"Запись {i}",
                author=self.owner,
            )
            for i in range(7)
        ]
        self.client.force_login(self.owner)

        response = self.client.get(reverse("clients_web:parent-card", args=[self.parent.pk]))

        for log in logs:
            self.assertContains(response, str(log.id))

    def test_cannot_view_another_organizations_parent_card(self):
        other_org = Organization.objects.create(name="Другая студия", slug="another-studio")
        other_parent = ParentContact.objects.create(organization=other_org, full_name="Чужой")
        self.client.force_login(self.owner)

        response = self.client.get(reverse("clients_web:parent-card", args=[other_parent.pk]))

        self.assertEqual(response.status_code, 404)


class ParentCommunicationLogWebViewTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.parent = ParentContact.objects.create(organization=self.org, full_name="Мама")
        self.child = _make_child(self.org)
        ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=self.parent,
            role=ChildContact.Role.MOTHER,
        )
        self.unrelated_child = _make_child(self.org, name="Чужой ребёнок")
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

    def test_owner_logs_communication_for_linked_child(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("clients_web:parent-communication-create", args=[self.parent.pk]),
            {"child": str(self.child.pk), "channel": "call", "note": "Обсудили оплату"},
        )

        self.assertEqual(response.status_code, 302)
        log = CommunicationLog.objects.get(parent_contact=self.parent)
        self.assertEqual(log.child, self.child)
        self.assertEqual(log.author, self.owner)

    def test_cannot_log_communication_for_unrelated_child(self):
        # Форма предлагает только детей, уже привязанных к этому родителю —
        # иначе можно было бы записать звонок про совсем чужого ребёнка.
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("clients_web:parent-communication-create", args=[self.parent.pk]),
            {"child": str(self.unrelated_child.pk), "channel": "call", "note": "Test"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(CommunicationLog.objects.filter(parent_contact=self.parent).exists())

    def test_note_is_required(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("clients_web:parent-communication-create", args=[self.parent.pk]),
            {"child": str(self.child.pk), "channel": "call", "note": ""},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)

    def test_teacher_cannot_log_communication(self):
        self.client.force_login(self.teacher)

        response = self.client.post(
            reverse("clients_web:parent-communication-create", args=[self.parent.pk]),
            {"child": str(self.child.pk), "channel": "call", "note": "Test"},
        )

        self.assertEqual(response.status_code, 403)
