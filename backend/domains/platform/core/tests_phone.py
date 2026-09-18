"""
Нормализация телефонов (ТЗ п. 4.1) — три разных написания одного
казахстанского номера должны нормализоваться в одно и то же значение.
"""

from django.test import SimpleTestCase

from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number


class NormalizePhoneNumberTests(SimpleTestCase):
    def test_three_kazakhstani_spellings_normalize_to_the_same_value(self):
        self.assertEqual(normalize_phone_number("+7 701 123-45-67"), "+77011234567")
        self.assertEqual(normalize_phone_number("87011234567"), "+77011234567")
        self.assertEqual(normalize_phone_number("7 (701) 1234567"), "+77011234567")

    def test_ten_digits_without_country_code(self):
        self.assertEqual(normalize_phone_number("7011234567"), "+77011234567")

    def test_already_normalized_value_is_unchanged(self):
        self.assertEqual(normalize_phone_number("+77011234567"), "+77011234567")

    def test_invalid_number_raises(self):
        with self.assertRaises(InvalidPhoneNumberError):
            normalize_phone_number("12345")

    def test_wrong_country_code_raises(self):
        with self.assertRaises(InvalidPhoneNumberError):
            normalize_phone_number("+1 202 555 0173")

    def test_empty_value_raises(self):
        with self.assertRaises(InvalidPhoneNumberError):
            normalize_phone_number("")
