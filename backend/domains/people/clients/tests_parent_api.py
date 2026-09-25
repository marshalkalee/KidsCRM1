"""
API родителей для frontend2 (TRU-83): поиск в списке, дети в списке,
карточка (дети из разных филиалов, долг и оплаты), удаление только без
детей, сводная лента коммуникаций (?family=).
"""

import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, tag
from django.urls import reverse
from rest_framework.test import APIClient

from domains.money.subscriptions.debt import debt_by_child
from domains.money.subscriptions.sales import sell_subscription
from domains.money.subscriptions.subscription_types import create_type
from domains.platform.tenants.models import Branch, Direction, Organization

from .models import Child, ChildContact, CommunicationLog, ContactPhone, ParentContact

User = get_user_model()


class ParentFixtures(TestCase):
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
        self.center = Branch.objects.create(organization=self.org, name="Центральный")
        self.north = Branch.objects.create(organization=self.org, name="Северный")
        self.ballet = Direction.objects.create(organization=self.org, name="Балет")
        self.ballet.branches.add(self.center)
        self.gym = Direction.objects.create(organization=self.org, name="Гимнастика")
        self.gym.branches.add(self.north)
        self.parent = ParentContact.objects.create(
            organization=self.org, full_name="Айгерим Серикова", whatsapp="+77011112233"
        )
        ContactPhone.objects.create(parent_contact=self.parent, number="+77011112233")
        self.api = APIClient()

    def make_child(self, name, direction, **link):
        child = Child.objects.create(
            organization=self.org,
            full_name=name,
            birth_date=datetime.date(2018, 1, 1),
            gender=Child.Gender.FEMALE,
        )
        child.directions.add(direction)
        ChildContact.objects.create(
            child=child, parent_contact=self.parent, role=link.pop("role", "mother"), **link
        )
        return child

    def sell(self, child, direction, branch, paid):
        if not hasattr(self, "version"):
            self.version = create_type(
                self.org, name="8 занятий", price=25000, quota_sessions=8, duration_days=30
            ).versions.latest()
        sell_subscription(
            actor=self.owner,
            child=child,
            subscription_type_version=self.version,
            direction=direction,
            branch=branch,
            starts_on=datetime.date.today(),
            ends_on=datetime.date.today() + datetime.timedelta(days=30),
            paid_amount=Decimal(paid),
            payment_method="cash",
        )

    def card_url(self, parent=None):
        return reverse("clients:parent-contact-card", args=[(parent or self.parent).pk])


class ParentApiTests(ParentFixtures):
    def test_list_search_by_name_and_phone_with_children(self):
        self.make_child("Аружан", self.ballet)
        ParentContact.objects.create(organization=self.org, full_name="Другой")
        self.api.force_authenticate(self.owner)
        url = reverse("clients:parent-contact-list")

        by_name = self.api.get(url, {"q": "айгер"}).json()["results"]
        by_phone = self.api.get(url, {"q": "1112233"}).json()["results"]

        self.assertEqual([p["full_name"] for p in by_name], ["Айгерим Серикова"])
        self.assertEqual([p["full_name"] for p in by_phone], ["Айгерим Серикова"])
        self.assertEqual([c["full_name"] for c in by_name[0]["children"]], ["Аружан"])

    def test_card_shows_children_from_two_branches_and_total_debt(self):
        first = self.make_child("Аружан", self.ballet, is_payer=True)
        second = self.make_child("Алия", self.gym, role="mother")
        self.sell(first, self.ballet, self.center, 20000)
        self.sell(second, self.gym, self.north, 10000)
        self.api.force_authenticate(self.owner)

        data = self.api.get(self.card_url()).json()

        self.assertEqual(
            sorted((c["full_name"], c["branch_names"]) for c in data["children"]),
            [("Алия", "Северный"), ("Аружан", "Центральный")],
        )
        expected = sum(debt_by_child(self.org, [first.id, second.id]).values(), Decimal(0))
        self.assertEqual(Decimal(data["money"]["total_debt"]), expected)
        self.assertEqual(Decimal(data["money"]["total_debt"]), Decimal("20000"))
        self.assertEqual(len(data["money"]["payments"]), 2)
        self.assertEqual(data["money"]["payments"][0]["subscription_name"], "8 занятий")

    def test_teacher_sees_neither_phones_nor_money(self):
        self.make_child("Аружан", self.ballet)
        self.api.force_authenticate(self.teacher)

        card = self.api.get(self.card_url()).json()
        listing = self.api.get(reverse("clients:parent-contact-list")).json()["results"]

        self.assertIsNone(card["money"])
        self.assertNotIn("phones", card["parent"])
        self.assertNotIn("whatsapp", card["parent"])
        self.assertNotIn("phones", listing[0])
        self.assertFalse(card["permissions"]["can_edit"])

    def test_cannot_delete_parent_with_children(self):
        self.make_child("Аружан", self.ballet)
        self.api.force_authenticate(self.owner)

        response = self.api.delete(reverse("clients:parent-contact-detail", args=[self.parent.pk]))

        self.assertEqual(response.status_code, 400)
        self.assertTrue(ParentContact.objects.filter(pk=self.parent.pk).exists())

    def test_deletes_parent_without_children_softly(self):
        self.api.force_authenticate(self.owner)

        response = self.api.delete(reverse("clients:parent-contact-detail", args=[self.parent.pk]))

        self.assertEqual(response.status_code, 204)
        self.assertFalse(ParentContact.objects.filter(pk=self.parent.pk).exists())
        self.assertTrue(ParentContact._base_manager.filter(pk=self.parent.pk).exists())

    def test_family_feed_includes_logs_of_all_children(self):
        first = self.make_child("Аружан", self.ballet)
        second = self.make_child("Алия", self.gym)
        stranger = Child.objects.create(
            organization=self.org,
            full_name="Чужой",
            birth_date=datetime.date(2017, 1, 1),
            gender=Child.Gender.MALE,
        )
        CommunicationLog.objects.create(child=first, note="про Аружан", author=self.owner)
        CommunicationLog.objects.create(child=second, note="про Алию", author=self.owner)
        CommunicationLog.objects.create(child=stranger, note="не наше", author=self.owner)
        self.api.force_authenticate(self.owner)

        rows = self.api.get(
            reverse("clients:communication-log-list"), {"family": str(self.parent.pk)}
        ).json()["results"]
        bad = self.api.get(reverse("clients:communication-log-list"), {"family": "не-uuid"})

        self.assertEqual(sorted(r["note"] for r in rows), ["про Алию", "про Аружан"])
        self.assertEqual(bad.status_code, 200)
        self.assertEqual(bad.json()["results"], [])

    @tag("tenant_isolation")
    def test_other_organization_parent_card_is_404(self):
        other = Organization.objects.create(name="Other", slug="other")
        foreign = ParentContact.objects.create(organization=other, full_name="Чужой")
        self.api.force_authenticate(self.owner)

        self.assertEqual(self.api.get(self.card_url(foreign)).status_code, 404)


class ParentDeleteWebTests(ParentFixtures):
    """Та же проверка в старом вебе (parent_delete)."""

    def test_web_delete_blocked_when_children_linked(self):
        self.make_child("Аружан", self.ballet)
        self.client.force_login(self.owner)

        response = self.client.post(reverse("clients_web:parent-delete", args=[self.parent.pk]))

        self.assertRedirects(response, reverse("clients_web:parent-card", args=[self.parent.pk]))
        self.assertTrue(ParentContact.objects.filter(pk=self.parent.pk).exists())
