"""
Веб-экран "Контакты ребёнка" (серверный рендеринг, сессия — см.
web_views.py). Часть тикета "Связь родитель <-> ребёнок: роли и
плательщик" — "Экран управления контактами в карточке ребёнка: список
контактов, добавление, назначение плательщика".
"""

import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from domains.platform.tenants.models import Organization

from .models import Child, ChildContact, ParentContact

User = get_user_model()


class ChildContactsWebViewTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.child = Child.objects.create(
            organization=self.org,
            full_name="Аружан",
            birth_date=datetime.date.today() - datetime.timedelta(days=365 * 7),
            gender=Child.Gender.FEMALE,
        )
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

    def test_owner_sees_contacts_list(self):
        link = ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=self.mother,
            role=ChildContact.Role.MOTHER,
        )
        self.client.force_login(self.owner)

        response = self.client.get(reverse("clients_web:child-contacts", args=[self.child.pk]))

        self.assertEqual(response.status_code, 200)
        # Список рендерится на клиенте из json_script — проверяем, что
        # строка связи попала в данные, а не литеральный текст имени в HTML.
        self.assertContains(response, str(link.pk))
        self.assertContains(response, "\\u041c\\u0430\\u043c\\u0430")  # "Мама"

    def test_owner_attaches_contact_via_web_form(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("clients_web:child-contact-create", args=[self.child.pk]),
            {
                "parent_contact": str(self.mother.pk),
                "role": "mother",
                "is_payer": "on",
                "is_primary_contact": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        link = ChildContact.objects.get(child=self.child, parent_contact=self.mother)
        self.assertTrue(link.is_payer)
        self.assertTrue(link.is_primary_contact)

    def test_teacher_cannot_attach_contact(self):
        self.client.force_login(self.teacher)

        response = self.client.get(
            reverse("clients_web:child-contact-create", args=[self.child.pk])
        )

        self.assertEqual(response.status_code, 403)

    def test_teacher_can_view_contacts_list(self):
        self.client.force_login(self.teacher)

        response = self.client.get(reverse("clients_web:child-contacts", args=[self.child.pk]))

        self.assertEqual(response.status_code, 200)

    def test_owner_detaches_contact(self):
        link = ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=self.mother,
            role=ChildContact.Role.MOTHER,
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("clients_web:child-contact-detach", args=[self.child.pk, link.pk])
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(ChildContact.objects.filter(pk=link.pk).exists())

    def test_ajax_get_returns_form_fragment_not_full_page(self):
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("clients_web:child-contact-create", args=[self.child.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"<html", response.content)
        self.assertIn(b'name="parent_contact"', response.content)

    def test_attaching_same_parent_twice_via_web_form_is_rejected(self):
        ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=self.mother,
            role=ChildContact.Role.MOTHER,
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("clients_web:child-contact-create", args=[self.child.pk]),
            {"parent_contact": str(self.mother.pk), "role": "guardian"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "уже привязан")
        self.assertEqual(ChildContact.objects.filter(child=self.child).count(), 1)
