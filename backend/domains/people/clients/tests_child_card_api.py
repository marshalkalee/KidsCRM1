"""
API карточки ребёнка для frontend2 (TRU-82): шапка (children/<id>/card/),
вкладка «Контакты» (child-contacts с телефонами) и «Коммуникации»
(communications, append-only).
"""

import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, tag
from django.urls import reverse
from rest_framework.test import APIClient

from domains.money.subscriptions.sales import sell_subscription
from domains.money.subscriptions.subscription_types import create_type
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.scheduling.groups.models import Group, GroupMembership

from .models import Child, ChildContact, CommunicationLog, ContactPhone, ParentContact

User = get_user_model()


def make_user(org, phone, role):
    return User.objects.create_user(
        phone=phone, full_name=role.title(), password="pass12345", organization=org, role=role
    )


class ChildCardApiBase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.owner = make_user(self.org, "+77010000001", User.Role.OWNER)
        self.teacher = make_user(self.org, "+77010000002", User.Role.TEACHER)
        self.branch = Branch.objects.create(organization=self.org, name="Центральный")
        self.direction = Direction.objects.create(organization=self.org, name="Балет")
        self.direction.branches.add(self.branch)
        self.child = Child.objects.create(
            organization=self.org,
            full_name="Аружан",
            birth_date=datetime.date(2018, 3, 12),
            gender=Child.Gender.FEMALE,
            leave_reason="",
            consent_given=True,
        )
        self.child.directions.add(self.direction)
        self.mother = ParentContact.objects.create(organization=self.org, full_name="Мама")
        ContactPhone.objects.create(parent_contact=self.mother, number="+77011112233")
        self.father = ParentContact.objects.create(organization=self.org, full_name="Папа")
        self.api = APIClient()

    def link(self, parent, **extra):
        return ChildContact.objects.create(
            child=self.child, parent_contact=parent, role=extra.pop("role", "mother"), **extra
        )


class ChildCardSummaryTests(ChildCardApiBase):
    def url(self, child=None):
        return reverse("clients:child-card", args=[(child or self.child).pk])

    def test_owner_gets_header_with_money(self):
        group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Младшая",
            capacity=10,
        )
        GroupMembership.objects.create(
            organization=self.org, group=group, child=self.child, joined_at=datetime.date.today()
        )
        sub_type = create_type(
            self.org, name="8 занятий", price=25000, quota_sessions=8, duration_days=30
        )
        sell_subscription(
            actor=self.owner,
            child=self.child,
            subscription_type_version=sub_type.versions.latest(),
            direction=self.direction,
            branch=self.branch,
            starts_on=datetime.date.today(),
            ends_on=datetime.date.today() + datetime.timedelta(days=30),
            paid_amount=Decimal("20000"),
            payment_method="cash",
        )
        self.api.force_authenticate(self.owner)

        data = self.api.get(self.url()).json()

        self.assertEqual(data["child"]["full_name"], "Аружан")
        self.assertEqual([b["name"] for b in data["branches"]], ["Центральный"])
        self.assertEqual([d["name"] for d in data["directions"]], ["Балет"])
        self.assertEqual([g["name"] for g in data["groups"]], ["Младшая"])
        self.assertEqual(Decimal(data["money"]["debt"]), Decimal("5000"))
        self.assertEqual(data["money"]["subscription"]["name"], "8 занятий")
        self.assertTrue(data["permissions"]["can_edit"])

    def test_teacher_gets_no_money_and_no_sensitive_fields(self):
        self.api.force_authenticate(self.teacher)

        data = self.api.get(self.url()).json()

        self.assertIsNone(data["money"])
        self.assertNotIn("leave_reason", data["child"])
        self.assertNotIn("consent_given", data["child"])
        self.assertFalse(data["permissions"]["can_edit"])
        self.assertFalse(data["permissions"]["can_log_communications"])

    @tag("tenant_isolation")
    def test_other_organization_child_is_404(self):
        other = Organization.objects.create(name="Other", slug="other")
        foreign = Child.objects.create(
            organization=other,
            full_name="Чужой",
            birth_date=datetime.date(2018, 1, 1),
            gender=Child.Gender.MALE,
        )
        self.api.force_authenticate(self.owner)

        self.assertEqual(self.api.get(self.url(foreign)).status_code, 404)

    def test_teacher_cannot_edit_child(self):
        self.api.force_authenticate(self.teacher)
        response = self.api.patch(
            reverse("clients:child-detail", args=[self.child.pk]), {"full_name": "X"}
        )
        self.assertEqual(response.status_code, 403)


class ChildContactsTabTests(ChildCardApiBase):
    url = reverse("clients:child-contact-list")

    def test_owner_sees_parent_phones(self):
        self.link(self.mother, is_payer=True)
        self.api.force_authenticate(self.owner)

        rows = self.api.get(self.url, {"child": str(self.child.pk)}).json()["results"]

        self.assertEqual(rows[0]["parent_contact_full_name"], "Мама")
        self.assertEqual(rows[0]["parent_contact_phones"][0]["number"], "+77011112233")

    def test_teacher_does_not_see_phones(self):
        self.link(self.mother)
        self.api.force_authenticate(self.teacher)

        row = self.api.get(self.url, {"child": str(self.child.pk)}).json()["results"][0]

        self.assertNotIn("parent_contact_phones", row)
        self.assertNotIn("parent_contact_whatsapp", row)

    def test_new_payer_takes_flag_from_previous(self):
        mother_link = self.link(self.mother, is_payer=True)
        self.api.force_authenticate(self.owner)

        response = self.api.post(
            self.url,
            {
                "child": str(self.child.pk),
                "parent_contact": str(self.father.pk),
                "role": "father",
                "is_payer": True,
            },
        )

        self.assertEqual(response.status_code, 201, response.content)
        mother_link.refresh_from_db()
        self.assertFalse(mother_link.is_payer)

    def test_detach_is_soft(self):
        link = self.link(self.mother)
        self.api.force_authenticate(self.owner)

        response = self.api.delete(reverse("clients:child-contact-detail", args=[link.pk]))

        self.assertEqual(response.status_code, 204)
        self.assertTrue(ChildContact._base_manager.filter(pk=link.pk).exists())
        self.assertTrue(ParentContact.objects.filter(pk=self.mother.pk).exists())

    def test_query_count_does_not_grow_with_contacts(self):
        self.link(self.mother)
        self.api.force_authenticate(self.owner)
        with self.assertNumQueries(3):
            self.api.get(self.url, {"child": str(self.child.pk)})
        self.link(self.father, role="father")
        ContactPhone.objects.create(parent_contact=self.father, number="+77019998877")
        with self.assertNumQueries(3):
            self.api.get(self.url, {"child": str(self.child.pk)})


class CommunicationLogApiTests(ChildCardApiBase):
    url = reverse("clients:communication-log-list")

    def test_owner_creates_log_with_self_as_author(self):
        self.link(self.mother)
        self.api.force_authenticate(self.owner)

        response = self.api.post(
            self.url,
            {
                "child": str(self.child.pk),
                "parent_contact": str(self.mother.pk),
                "channel": "whatsapp",
                "note": "  Напомнили про оплату  ",
            },
        )

        self.assertEqual(response.status_code, 201, response.content)
        log = CommunicationLog.objects.get()
        self.assertEqual(log.author, self.owner)
        self.assertEqual(log.note, "Напомнили про оплату")
        self.assertEqual(response.json()["author_name"], self.owner.full_name)
        self.assertEqual(response.json()["channel_label"], "WhatsApp")

    def test_list_filters_by_child_and_parent(self):
        self.link(self.mother)
        other_child = Child.objects.create(
            organization=self.org,
            full_name="Брат",
            birth_date=datetime.date(2016, 1, 1),
            gender=Child.Gender.MALE,
        )
        CommunicationLog.objects.create(
            child=self.child, parent_contact=self.mother, note="по Аружан", author=self.owner
        )
        CommunicationLog.objects.create(child=other_child, note="по брату", author=self.owner)
        self.api.force_authenticate(self.teacher)

        by_child = self.api.get(self.url, {"child": str(self.child.pk)}).json()["results"]
        by_parent = self.api.get(self.url, {"parent_contact": str(self.mother.pk)}).json()

        self.assertEqual([r["note"] for r in by_child], ["по Аружан"])
        self.assertEqual([r["note"] for r in by_parent["results"]], ["по Аружан"])

    def test_teacher_cannot_create(self):
        self.api.force_authenticate(self.teacher)
        response = self.api.post(self.url, {"child": str(self.child.pk), "note": "x"})
        self.assertEqual(response.status_code, 403)

    def test_parent_must_be_linked_to_child(self):
        self.api.force_authenticate(self.owner)
        response = self.api.post(
            self.url,
            {"child": str(self.child.pk), "parent_contact": str(self.father.pk), "note": "x"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("parent_contact", response.json())

    def test_blank_note_is_rejected(self):
        self.api.force_authenticate(self.owner)
        response = self.api.post(self.url, {"child": str(self.child.pk), "note": "   "})
        self.assertEqual(response.status_code, 400)

    def test_log_is_append_only(self):
        log = CommunicationLog.objects.create(child=self.child, note="x", author=self.owner)
        self.api.force_authenticate(self.owner)
        detail = reverse("clients:communication-log-detail", args=[log.pk])

        self.assertEqual(self.api.patch(detail, {"note": "y"}).status_code, 405)
        self.assertEqual(self.api.delete(detail).status_code, 405)

    @tag("tenant_isolation")
    def test_cannot_log_for_other_organization_child(self):
        other = Organization.objects.create(name="Other", slug="other")
        foreign = Child.objects.create(
            organization=other,
            full_name="Чужой",
            birth_date=datetime.date(2018, 1, 1),
            gender=Child.Gender.MALE,
        )
        CommunicationLog.objects.create(
            child=foreign, note="чужое", author=make_user(other, "+77010000077", "owner")
        )
        self.api.force_authenticate(self.owner)

        create = self.api.post(self.url, {"child": str(foreign.pk), "note": "x"})
        listing = self.api.get(self.url).json()["results"]

        self.assertEqual(create.status_code, 400)
        self.assertEqual(listing, [])
