"""
ChildService (TRU-8, контракт №2) — поиск дублей и создание связки
ребёнок+родитель. Критерий приёмки: тесты на все сценарии, включая
"тот же телефон, другой ребёнок" (см. test_phone_match_different_child_
is_not_a_duplicate_but_signals_existing_parent — это и есть тот случай).
"""

from datetime import date

from django.test import TestCase

from domains.platform.tenants.models import Organization

from .models import Child, ChildContact, ContactPhone, ParentContact
from .services import ChildService, DuplicateReason


def _child_data(name="Айгерим Серикова", **extra):
    defaults = {
        "full_name": name,
        "birth_date": date(2018, 3, 10),
        "gender": Child.Gender.FEMALE,
    }
    defaults.update(extra)
    return defaults


class FindDuplicatesTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")

    def _make_family(self, parent_name="Иванова Марина", phone="+77011234567", children=()):
        parent = ParentContact.objects.create(organization=self.org, full_name=parent_name)
        if phone:
            ContactPhone.objects.create(organization=self.org, parent_contact=parent, number=phone)
        for child in children:
            ChildContact.objects.create(
                organization=self.org,
                child=child,
                parent_contact=parent,
                role=ChildContact.Role.MOTHER,
            )
        return parent

    def test_no_matches_when_nothing_matches(self):
        matches = ChildService.find_duplicates(
            self.org, phone="+77011234567", child_name="Кто-то", birth_date=date(2020, 1, 1)
        )

        self.assertEqual(matches, [])

    def test_phone_match_same_child_is_a_duplicate(self):
        child = Child.objects.create(organization=self.org, **_child_data())
        self._make_family(phone="+77011234567", children=[child])

        matches = ChildService.find_duplicates(
            self.org,
            phone="+7 (701) 123-45-67",
            child_name="Айгерим Серикова",
            birth_date=date(2018, 3, 10),
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].reason, DuplicateReason.PHONE)
        self.assertEqual(matches[0].child.id, child.id)

    def test_phone_match_different_child_is_not_a_duplicate_but_signals_existing_parent(self):
        # Критический сценарий из тикета: тот же телефон, но другой
        # ребёнок — это второй ребёнок в семье, НЕ дубль.
        existing_child = Child.objects.create(organization=self.org, **_child_data("Данияр"))
        parent = self._make_family(phone="+77011234567", children=[existing_child])

        matches = ChildService.find_duplicates(
            self.org,
            phone="+77011234567",
            child_name="Айгерим Серикова",  # другое имя — новый ребёнок
            birth_date=date(2019, 5, 1),
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].reason, DuplicateReason.EXISTING_PARENT_NEW_CHILD)
        self.assertIsNone(matches[0].child)
        self.assertEqual(matches[0].parent.id, parent.id)

    def test_phone_match_without_name_or_birth_date_signals_existing_parent(self):
        # Без имени/даты рождения сервис не может решить, тот же это
        # ребёнок или новый — сигнал "есть такая семья" всё равно нужен.
        existing_child = Child.objects.create(organization=self.org, **_child_data("Данияр"))
        parent = self._make_family(phone="+77011234567", children=[existing_child])

        matches = ChildService.find_duplicates(self.org, phone="+77011234567")

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].reason, DuplicateReason.EXISTING_PARENT_NEW_CHILD)
        self.assertEqual(matches[0].parent.id, parent.id)

    def test_phone_matches_only_the_correct_child_when_family_has_several(self):
        match_child = Child.objects.create(organization=self.org, **_child_data("Айгерим Серикова"))
        other_child = Child.objects.create(organization=self.org, **_child_data("Данияр"))
        self._make_family(phone="+77011234567", children=[match_child, other_child])

        matches = ChildService.find_duplicates(
            self.org,
            phone="+77011234567",
            child_name="Айгерим Серикова",
            birth_date=date(2018, 3, 10),
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].reason, DuplicateReason.PHONE)
        self.assertEqual(matches[0].child.id, match_child.id)

    def test_name_and_birth_date_match_without_phone(self):
        child = Child.objects.create(organization=self.org, **_child_data())

        matches = ChildService.find_duplicates(
            self.org, child_name="Айгерим Серикова", birth_date=date(2018, 3, 10)
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].reason, DuplicateReason.NAME_AND_BIRTH_DATE)
        self.assertEqual(matches[0].child.id, child.id)

    def test_name_and_birth_date_match_is_case_insensitive(self):
        child = Child.objects.create(organization=self.org, **_child_data())

        matches = ChildService.find_duplicates(
            self.org, child_name="айгерим серикова", birth_date=date(2018, 3, 10)
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].child.id, child.id)

    def test_name_only_match_when_birth_date_differs(self):
        child = Child.objects.create(organization=self.org, **_child_data())

        matches = ChildService.find_duplicates(
            self.org, child_name="Айгерим Серикова", birth_date=date(2000, 1, 1)
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].reason, DuplicateReason.NAME_ONLY)
        self.assertEqual(matches[0].child.id, child.id)

    def test_name_only_match_without_birth_date_given(self):
        child = Child.objects.create(organization=self.org, **_child_data())

        matches = ChildService.find_duplicates(self.org, child_name="Айгерим Серикова")

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].reason, DuplicateReason.NAME_ONLY)
        self.assertEqual(matches[0].child.id, child.id)

    def test_child_matched_by_name_and_birth_date_is_not_duplicated_as_name_only(self):
        Child.objects.create(organization=self.org, **_child_data())

        matches = ChildService.find_duplicates(
            self.org, child_name="Айгерим Серикова", birth_date=date(2018, 3, 10)
        )

        self.assertEqual(len(matches), 1)

    def test_child_matched_by_phone_is_not_duplicated_by_name_and_birth_date(self):
        child = Child.objects.create(organization=self.org, **_child_data())
        self._make_family(phone="+77011234567", children=[child])

        matches = ChildService.find_duplicates(
            self.org,
            phone="+77011234567",
            child_name="Айгерим Серикова",
            birth_date=date(2018, 3, 10),
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].reason, DuplicateReason.PHONE)

    def test_invalid_phone_is_ignored_not_raised(self):
        child = Child.objects.create(organization=self.org, **_child_data())

        matches = ChildService.find_duplicates(
            self.org,
            phone="не телефон",
            child_name="Айгерим Серикова",
            birth_date=date(2018, 3, 10),
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].reason, DuplicateReason.NAME_AND_BIRTH_DATE)
        self.assertEqual(matches[0].child.id, child.id)

    def test_tenant_isolation(self):
        other_org = Organization.objects.create(name="Other", slug="other")
        other_child = Child.objects.create(organization=other_org, **_child_data())
        ParentContact.objects.create(organization=other_org, full_name="Чужая")

        matches = ChildService.find_duplicates(
            self.org,
            phone="+77011234567",
            child_name="Айгерим Серикова",
            birth_date=date(2018, 3, 10),
        )

        self.assertEqual(matches, [])
        self.assertTrue(Child.objects.filter(pk=other_child.pk).exists())


class CreateWithParentTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")

    def test_creates_child_new_parent_and_link(self):
        child = ChildService.create_with_parent(
            self.org,
            child_data=_child_data("Данияр"),
            parent_data={
                "full_name": "Иванова Марина",
                "phones": ["+77011234567"],
                "email": "marina@example.com",
            },
            link_role=ChildContact.Role.MOTHER,
        )

        self.assertEqual(child.organization, self.org)
        self.assertEqual(child.full_name, "Данияр")

        link = ChildContact.objects.get(child=child)
        self.assertEqual(link.parent_contact.full_name, "Иванова Марина")
        self.assertEqual(link.parent_contact.email, "marina@example.com")
        self.assertTrue(link.is_primary_contact)
        self.assertTrue(link.is_payer)
        self.assertEqual(link.role, ChildContact.Role.MOTHER)
        self.assertEqual(
            list(link.parent_contact.phones.values_list("number", flat=True)), ["+77011234567"]
        )

    def test_second_child_attaches_to_existing_parent_instead_of_creating_a_new_one(self):
        # Ровно тот путь, которым второй ребёнок в семье должен попадать
        # в систему — без него было бы две мамы с одним номером.
        first_child = ChildService.create_with_parent(
            self.org,
            child_data=_child_data("Данияр"),
            parent_data={"full_name": "Иванова Марина", "phones": ["+77011234567"]},
            link_role=ChildContact.Role.MOTHER,
        )
        existing_parent = ChildContact.objects.get(child=first_child).parent_contact

        second_child = ChildService.create_with_parent(
            self.org,
            child_data=_child_data("Айгерим Серикова"),
            parent_data={"id": str(existing_parent.id)},
            link_role=ChildContact.Role.MOTHER,
        )

        self.assertEqual(ParentContact.objects.for_tenant(self.org).count(), 1)
        second_link = ChildContact.objects.get(child=second_child)
        self.assertEqual(second_link.parent_contact.id, existing_parent.id)
        self.assertTrue(second_link.is_primary_contact)
        self.assertTrue(second_link.is_payer)

    def test_create_without_phones_key_does_not_fail(self):
        child = ChildService.create_with_parent(
            self.org,
            child_data=_child_data("Данияр"),
            parent_data={"full_name": "Иванова Марина"},
            link_role=ChildContact.Role.MOTHER,
        )

        parent = ChildContact.objects.get(child=child).parent_contact
        self.assertEqual(parent.phones.count(), 0)

    def test_existing_parent_id_from_other_organization_is_not_found(self):
        other_org = Organization.objects.create(name="Other", slug="other")
        foreign_parent = ParentContact.objects.create(organization=other_org, full_name="Чужая")

        with self.assertRaises(ParentContact.DoesNotExist):
            ChildService.create_with_parent(
                self.org,
                child_data=_child_data("Данияр"),
                parent_data={"id": str(foreign_parent.id)},
                link_role=ChildContact.Role.MOTHER,
            )

    def test_failure_rolls_back_the_whole_creation(self):
        with self.assertRaises(ParentContact.DoesNotExist):
            ChildService.create_with_parent(
                self.org,
                child_data=_child_data("Данияр"),
                parent_data={"id": "00000000-0000-0000-0000-000000000000"},
                link_role=ChildContact.Role.MOTHER,
            )

        self.assertFalse(Child.objects.filter(full_name="Данияр").exists())
