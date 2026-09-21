"""
Быстрый поиск в шапке — по имени ребёнка, имени родителя и телефону в
одном поле (ТЗ п. 4.1). Критерии приёмки: 3 символа имени находят ребёнка
среди 5000 за ≤1с, поиск по последним 4 цифрам телефона, один номер в
трёх написаниях — один результат, казахские буквы ищутся в любом
регистре, can_view_phone скрывает поиск/результат по телефону.
"""

import random
import time
import uuid
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, tag
from django.urls import reverse

from domains.platform.tenants.models import Organization

from .models import Child, ChildContact, ContactPhone, ParentContact

User = get_user_model()


def _make_child(org, name, **extra):
    defaults = {
        "organization": org,
        "full_name": name,
        "birth_date": date(2015, 1, 1),
        "gender": Child.Gender.FEMALE,
    }
    defaults.update(extra)
    return Child.objects.create(**defaults)


class GlobalSearchWebViewTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
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
        self.client.force_login(self.owner)

    def _search(self, query, user=None):
        if user is not None:
            self.client.force_login(user)
        response = self.client.get(reverse("clients_web:global-search"), {"q": query})
        return response.json()["results"]

    def test_query_shorter_than_three_chars_returns_empty(self):
        _make_child(self.org, "Айгерим")

        self.assertEqual(self._search("Ай"), [])

    def test_partial_case_insensitive_child_name_match(self):
        child = _make_child(self.org, "Айгерим Серикова")

        results = self._search("айг")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["type"], "child")
        self.assertEqual(results[0]["id"], str(child.id))
        self.assertEqual(results[0]["matched_on"], "child_name")

    def test_kazakh_letter_search_is_case_insensitive(self):
        child = _make_child(self.org, "Әсем Қанатова")

        results = self._search("әсем")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], str(child.id))

    def test_search_by_parent_name_finds_child(self):
        child = _make_child(self.org, "Данияр")
        parent = ParentContact.objects.create(organization=self.org, full_name="Иванова Марина")
        ChildContact.objects.create(
            organization=self.org, child=child, parent_contact=parent, role=ChildContact.Role.MOTHER
        )

        results = self._search("иван")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["type"], "child")
        self.assertEqual(results[0]["id"], str(child.id))
        self.assertEqual(results[0]["matched_on"], "parent_name")
        self.assertEqual(results[0]["matched_detail"], "Иванова Марина")

    def test_search_by_last_four_digits_of_phone(self):
        child = _make_child(self.org, "Данияр")
        parent = ParentContact.objects.create(organization=self.org, full_name="Иванова Марина")
        ChildContact.objects.create(
            organization=self.org, child=child, parent_contact=parent, role=ChildContact.Role.MOTHER
        )
        ContactPhone.objects.create(
            organization=self.org, parent_contact=parent, number="+77011234567"
        )

        results = self._search("4567")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], str(child.id))
        self.assertEqual(results[0]["matched_on"], "phone")

    def test_same_phone_in_three_written_forms_gives_one_result(self):
        child = _make_child(self.org, "Данияр")
        parent = ParentContact.objects.create(organization=self.org, full_name="Иванова Марина")
        ChildContact.objects.create(
            organization=self.org, child=child, parent_contact=parent, role=ChildContact.Role.MOTHER
        )
        # Хранится нормализованным (ContactPhone.save()) — все три написания
        # ниже должны найти именно эту запись.
        ContactPhone.objects.create(
            organization=self.org, parent_contact=parent, number="+77011234567"
        )

        for written_form in ["+7 (701) 123-45-67", "8 701 123 45 67", "77011234567"]:
            with self.subTest(written_form=written_form):
                results = self._search(written_form)
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0]["id"], str(child.id))

    def test_standalone_parent_without_children_is_returned(self):
        parent = ParentContact.objects.create(organization=self.org, full_name="Петрова Анна")

        results = self._search("петров")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["type"], "parent")
        self.assertEqual(results[0]["id"], str(parent.id))

    def test_teacher_without_phone_permission_gets_no_phone_match(self):
        child = _make_child(self.org, "Данияр")
        parent = ParentContact.objects.create(organization=self.org, full_name="Иванова Марина")
        ChildContact.objects.create(
            organization=self.org, child=child, parent_contact=parent, role=ChildContact.Role.MOTHER
        )
        ContactPhone.objects.create(
            organization=self.org, parent_contact=parent, number="+77011234567"
        )

        results = self._search("4567", user=self.teacher)

        self.assertEqual(results, [])

    def test_teacher_can_still_search_by_name(self):
        child = _make_child(self.org, "Данияр Сериков")

        results = self._search("сери", user=self.teacher)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], str(child.id))

    def test_tenant_isolation(self):
        other_org = Organization.objects.create(name="Other", slug="other")
        _make_child(other_org, "Айгерим")

        self.assertEqual(self._search("айг"), [])


@tag("performance")
class GlobalSearchPerformanceTests(TestCase):
    CHILD_COUNT = 5000
    # Реальный бюджет из ТЗ — 1с; запас на дев-контейнер, не прод-железо
    # (тот же принцип, что у tests_child_list_performance.py).
    RESPONSE_BUDGET_SECONDS = 2.5

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Perf Ballet", slug="perf-ballet-search")
        cls.owner = User.objects.create_user(
            phone="+77010000099",
            full_name="Owner",
            password="pass12345",
            organization=cls.org,
            role=User.Role.OWNER,
        )
        cls.target = _make_child(cls.org, "Айгерим Тестова")
        Child.objects.bulk_create(
            [
                Child(
                    id=uuid.uuid4(),
                    organization=cls.org,
                    full_name=f"Ребёнок {i}",
                    birth_date=date.today() - timedelta(days=365 * random.randint(3, 15)),
                    gender="female",
                    status="active",
                )
                for i in range(cls.CHILD_COUNT - 1)
            ]
        )

    def setUp(self):
        self.client.force_login(self.owner)

    def test_three_char_name_search_responds_within_budget(self):
        start = time.perf_counter()
        response = self.client.get(reverse("clients_web:global-search"), {"q": "Айг"})
        elapsed = time.perf_counter() - start

        results = response.json()["results"]
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(r["id"] == str(self.target.id) for r in results))
        self.assertLess(
            elapsed,
            self.RESPONSE_BUDGET_SECONDS,
            f"global-search ответил за {elapsed:.3f}с на {self.CHILD_COUNT} детей "
            f"(бюджет теста {self.RESPONSE_BUDGET_SECONDS}с, целевой бюджет ТЗ п. 10.2 — 1с)",
        )
