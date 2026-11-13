"""Кабинет родителя: кнопки WhatsApp ведут на подключённый номер центра."""

from datetime import date
from urllib.parse import unquote

from django.test import TestCase

from domains.people.clients.models import Child
from domains.platform.notifications.models import WhatsAppConnection
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.scheduling.groups.models import Group, GroupMembership

from . import money
from .center import center


class PortalWhatsAppLinksTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="portal-wa")
        self.abaya = Branch.objects.create(organization=self.org, name="Абая", phone="+77272000000")
        self.orbita = Branch.objects.create(organization=self.org, name="Орбита", phone="")
        ballet = Direction.objects.create(organization=self.org, name="Балет")
        group = Group.objects.create(
            organization=self.org, branch=self.abaya, direction=ballet, name="Балет", capacity=12
        )
        self.child = Child.objects.create(
            organization=self.org, full_name="Милана Исаева", birth_date=date(2017, 1, 1)
        )
        GroupMembership.objects.create(
            organization=self.org, child=self.child, group=group, joined_at=date(2026, 9, 1)
        )

    def number(self, branch, phone):
        return WhatsAppConnection.objects.create(
            organization=self.org,
            branch=branch,
            mode=WhatsAppConnection.Mode.EVOLUTION,
            status=WhatsAppConnection.Status.CONNECTED,
            business_phone=phone,
        )

    def branch_url(self, name):
        return next(b for b in center(self.child)["branches"] if b["name"] == name)["whatsapp_url"]

    def test_without_whatsapp_branch_phone_is_used_as_before(self):
        self.assertEqual(self.branch_url("Абая"), "https://wa.me/77272000000")
        self.assertEqual(self.branch_url("Орбита"), "")

    def test_branch_number_then_center_number(self):
        self.number(None, "+77070000001")
        self.number(self.abaya, "+77070000002")
        self.assertEqual(self.branch_url("Абая"), "https://wa.me/77070000002")
        # У Орбиты своего номера нет — пишут на номер всего центра.
        self.assertEqual(self.branch_url("Орбита"), "https://wa.me/77070000001")

    def test_disconnected_number_is_not_used(self):
        connection = self.number(self.abaya, "+77070000002")
        connection.status = WhatsAppConnection.Status.DISCONNECTED
        connection.save()
        self.assertEqual(self.branch_url("Абая"), "https://wa.me/77272000000")

    def test_payment_question_has_ready_text(self):
        self.number(self.abaya, "+77070000002")
        row = money.contacts(self.child)[0]
        self.assertTrue(row["whatsapp_url"].startswith("https://wa.me/77070000002?text="))
        self.assertIn("Вопрос по оплате абонемента: Милана Исаева", unquote(row["whatsapp_url"]))
