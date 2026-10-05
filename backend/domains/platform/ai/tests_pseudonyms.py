"""Псевдонимы для внешней модели (ADR-0008): имена клиентов → метки и обратно."""

import datetime

from django.test import TestCase

from domains.people.clients.models import Child, ParentContact
from domains.platform.leads.services import create_lead
from domains.platform.tenants.models import Organization
from domains.platform.users.models import User

from .pseudonyms import Pseudonymizer


class PseudonymizerTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="tb")
        self.staff = User.objects.create_user(
            phone="77010000001", password="x", full_name="Жумабекова Сауле", organization=self.org
        )
        Child.objects.create(
            organization=self.org, full_name="Исаева Сафия", birth_date=datetime.date(2015, 1, 1)
        )
        Child.objects.create(
            organization=self.org, full_name="Ким Мира", birth_date=datetime.date(2016, 1, 1)
        )
        ParentContact.objects.create(organization=self.org, full_name="Исаева Айгерим")
        create_lead(
            organization=self.org,
            actor=self.staff,
            parent_name="Сапарова Меруерт",
            phone="+77015554433",
            child_name="Тимурлан",
        )

    def test_full_names_and_parts(self):
        names = Pseudonymizer(self.org)
        text = names.mask("Исаева Сафия пропустила, Айгерим просила перезвонить; заявка Меруерт")
        for real in ("Исаева", "Сафия", "Айгерим", "Меруерт"):
            self.assertNotIn(real, text)
        self.assertEqual(
            names.unmask(text),
            "Исаева Сафия пропустила, Айгерим просила перезвонить; заявка Меруерт",
        )
        # Полное имя — одна метка.
        self.assertTrue(text.startswith("[N1] пропустила"), text)

    def test_declined_forms_get_the_same_label(self):
        names = Pseudonymizer(self.org)
        nominative = names.mask("Айгерим")
        self.assertEqual(names.mask("позвонить Айгерим"), f"позвонить {nominative}")
        declined = names.mask("Что с Исаевой Сафией? Долг у Тимурлана, написать Меруерт")
        for real in ("Исаев", "Сафи", "Тимурлан", "Меруерт"):
            self.assertNotIn(real, declined)
        self.assertEqual(names.mask("Сафия"), names.mask("Сафией"))
        # Обратно — именительный падеж.
        self.assertIn("Тимурлан", names.unmask(declined))

    def test_common_words_are_not_names(self):
        names = Pseudonymizer(self.org)
        # «Мира» — имя ребёнка, но «миру», «мире» в тексте — слова.
        self.assertEqual(names.mask("по всему миру и в мире"), "по всему миру и в мире")
        self.assertNotIn("Мира", names.mask("Мира пришла, Миру записали"))

    def test_staff_names_stay(self):
        """Сотрудники — не данные клиентов: модели нужно знать ответственного."""
        self.assertEqual(
            Pseudonymizer(self.org).mask("Ответственный: Жумабекова Сауле"),
            "Ответственный: Жумабекова Сауле",
        )

    def test_mapping_continues_between_requests(self):
        first = Pseudonymizer(self.org)
        label = first.mask("Исаева Сафия")
        second = Pseudonymizer(self.org, first.mapping)
        self.assertEqual(second.mask("Исаева Сафия"), label)
        self.assertEqual(second.mask("Меруерт"), "[N2]")
        self.assertEqual(second.unmask("[N99] и [N1]"), "[N99] и Исаева Сафия")

    def test_structures(self):
        names = Pseudonymizer(self.org)
        masked = names.mask(
            {"child": {"full_name": "Исаева Сафия", "age": 10}, "list": ["Айгерим"]}
        )
        self.assertEqual(masked["child"]["age"], 10)
        self.assertEqual(
            names.unmask(masked),
            {"child": {"full_name": "Исаева Сафия", "age": 10}, "list": ["Айгерим"]},
        )

    def test_other_org_names_are_not_known(self):
        other = Organization.objects.create(name="Другой", slug="other")
        self.assertEqual(Pseudonymizer(other).mask("Исаева Сафия"), "Исаева Сафия")
