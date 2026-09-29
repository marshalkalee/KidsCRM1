from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .text_validation import normalize_entity_name, normalize_person_name


class TextValidationTests(SimpleTestCase):
    def test_person_name_is_trimmed_and_keeps_supported_punctuation(self):
        self.assertEqual(normalize_person_name("  Алия   О'Коннор-Смит  "), "Алия О'Коннор-Смит")

    def test_person_name_rejects_digits_and_single_letter(self):
        for value in ("А1", "А"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                normalize_person_name(value)

    def test_entity_name_allows_digits_but_requires_two_characters(self):
        self.assertEqual(normalize_entity_name("  Группа   2 "), "Группа 2")
        with self.assertRaises(ValidationError):
            normalize_entity_name("Г")
