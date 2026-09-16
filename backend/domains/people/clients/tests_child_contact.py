"""
Связь родитель <-> ребёнок: роли и плательщик (ТЗ п. 1.2.1, п. 3.1).
Критерии приёмки:
- у ребёнка три контакта с разными ролями, плательщик — бабушка, основной
  контакт — мама;
- родитель с двумя детьми виден в связях обоих;
- отвязка контакта — мягкое удаление, не трогает ни Child, ни ParentContact;
- ровно один активный плательщик у ребёнка одновременно (согласовано с
  Bekzat — влияет на расчёт задолженности), то же для основного контакта;
- изоляция между организациями (тег tenant_isolation).
"""

import datetime

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, tag
from rest_framework import status
from rest_framework.test import APITestCase

from domains.platform.tenants.models import Organization

from .models import Child, ChildContact, ParentContact

User = get_user_model()


def _make_child(org, name="Аружан"):
    return Child.objects.create(
        organization=org,
        full_name=name,
        birth_date=datetime.date.today() - datetime.timedelta(days=365 * 7),
        gender=Child.Gender.FEMALE,
    )


class ChildContactModelTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.child = _make_child(self.org)
        self.mother = ParentContact.objects.create(organization=self.org, full_name="Мама")
        self.grandmother = ParentContact.objects.create(organization=self.org, full_name="Бабушка")

    def test_three_contacts_with_different_roles_payer_is_grandmother_primary_is_mother(self):
        father = ParentContact.objects.create(organization=self.org, full_name="Папа")

        mother_link = ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=self.mother,
            role=ChildContact.Role.MOTHER,
            is_primary_contact=True,
        )
        ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=father,
            role=ChildContact.Role.FATHER,
        )
        grandmother_link = ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=self.grandmother,
            role=ChildContact.Role.GRANDMOTHER,
            is_payer=True,
        )

        self.assertEqual(self.child.contacts.count(), 3)
        self.assertEqual(
            {link.role for link in self.child.contacts.all()},
            {ChildContact.Role.MOTHER, ChildContact.Role.FATHER, ChildContact.Role.GRANDMOTHER},
        )
        payer = self.child.contacts.get(is_payer=True)
        self.assertEqual(payer.pk, grandmother_link.pk)
        primary = self.child.contacts.get(is_primary_contact=True)
        self.assertEqual(primary.pk, mother_link.pk)

    def test_setting_new_payer_clears_previous_payer(self):
        old_payer = ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=self.mother,
            role=ChildContact.Role.MOTHER,
            is_payer=True,
        )

        new_payer = ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=self.grandmother,
            role=ChildContact.Role.GRANDMOTHER,
            is_payer=True,
        )

        old_payer.refresh_from_db()
        self.assertFalse(old_payer.is_payer)
        self.assertTrue(new_payer.is_payer)
        self.assertEqual(self.child.contacts.filter(is_payer=True).count(), 1)

    def test_setting_new_primary_contact_clears_previous(self):
        old_primary = ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=self.mother,
            role=ChildContact.Role.MOTHER,
            is_primary_contact=True,
        )

        new_primary = ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=self.grandmother,
            role=ChildContact.Role.GRANDMOTHER,
            is_primary_contact=True,
        )

        old_primary.refresh_from_db()
        self.assertFalse(old_primary.is_primary_contact)
        self.assertTrue(new_primary.is_primary_contact)

    def test_db_constraint_rejects_two_active_payers_created_around_the_orm(self):
        ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=self.mother,
            role=ChildContact.Role.MOTHER,
            is_payer=True,
        )
        second = ChildContact(
            organization=self.org,
            child=self.child,
            parent_contact=self.grandmother,
            role=ChildContact.Role.GRANDMOTHER,
            is_payer=True,
        )

        # Обходим save() (который сам бы снял старый флаг) — проверяем, что
        # инвариант всё равно держится на уровне БД (UniqueConstraint).
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ChildContact.objects.bulk_create([second])

    def test_parent_with_two_children_is_linked_to_both(self):
        second_child = _make_child(self.org, name="Данияр")

        ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=self.mother,
            role=ChildContact.Role.MOTHER,
        )
        ChildContact.objects.create(
            organization=self.org,
            child=second_child,
            parent_contact=self.mother,
            role=ChildContact.Role.MOTHER,
        )

        self.assertEqual(self.mother.child_links.count(), 2)
        linked_children = set(self.mother.child_links.values_list("child_id", flat=True))
        self.assertEqual(linked_children, {self.child.id, second_child.id})

    def test_detaching_contact_soft_deletes_link_only(self):
        link = ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=self.mother,
            role=ChildContact.Role.MOTHER,
        )

        link.delete()

        self.assertFalse(ChildContact.objects.filter(pk=link.pk).exists())
        self.child.refresh_from_db()
        self.mother.refresh_from_db()
        self.assertTrue(Child.objects.filter(pk=self.child.pk).exists())
        self.assertTrue(ParentContact.objects.filter(pk=self.mother.pk).exists())

    def test_reattaching_after_detach_is_allowed(self):
        link = ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=self.mother,
            role=ChildContact.Role.MOTHER,
        )
        link.delete()

        new_link = ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=self.mother,
            role=ChildContact.Role.MOTHER,
        )

        self.assertTrue(ChildContact.objects.filter(pk=new_link.pk).exists())


class ChildContactAPITests(APITestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.child = _make_child(self.org)
        self.mother = ParentContact.objects.create(organization=self.org, full_name="Мама")
        self.grandmother = ParentContact.objects.create(organization=self.org, full_name="Бабушка")
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

    def test_owner_attaches_existing_parent_to_child(self):
        self.client.force_authenticate(self.owner)

        response = self.client.post(
            "/api/v1/clients/child-contacts/",
            {
                "child": str(self.child.id),
                "parent_contact": str(self.mother.id),
                "role": "mother",
                "is_primary_contact": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["parent_contact_full_name"], "Мама")
        self.assertTrue(ChildContact.objects.filter(child=self.child, parent_contact=self.mother))

    def test_attaching_same_parent_twice_is_rejected(self):
        self.client.force_authenticate(self.owner)
        ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=self.mother,
            role=ChildContact.Role.MOTHER,
        )

        response = self.client.post(
            "/api/v1/clients/child-contacts/",
            {
                "child": str(self.child.id),
                "parent_contact": str(self.mother.id),
                "role": "guardian",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_change_role_via_patch(self):
        self.client.force_authenticate(self.owner)
        link = ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=self.mother,
            role=ChildContact.Role.MOTHER,
        )

        response = self.client.patch(
            f"/api/v1/clients/child-contacts/{link.id}/", {"role": "guardian"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        link.refresh_from_db()
        self.assertEqual(link.role, ChildContact.Role.GUARDIAN)

    def test_assign_payer_via_patch_clears_previous_payer(self):
        self.client.force_authenticate(self.owner)
        mother_link = ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=self.mother,
            role=ChildContact.Role.MOTHER,
            is_payer=True,
        )
        grandmother_link = ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=self.grandmother,
            role=ChildContact.Role.GRANDMOTHER,
        )

        response = self.client.patch(
            f"/api/v1/clients/child-contacts/{grandmother_link.id}/",
            {"is_payer": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        mother_link.refresh_from_db()
        grandmother_link.refresh_from_db()
        self.assertFalse(mother_link.is_payer)
        self.assertTrue(grandmother_link.is_payer)

    def test_detach_via_delete_is_soft_delete(self):
        self.client.force_authenticate(self.owner)
        link = ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=self.mother,
            role=ChildContact.Role.MOTHER,
        )

        response = self.client.delete(f"/api/v1/clients/child-contacts/{link.id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(ChildContact.objects.filter(pk=link.pk).exists())
        # Ни ребёнок, ни родитель не тронуты отвязкой.
        self.child.refresh_from_db()
        self.mother.refresh_from_db()

    def test_filter_by_child_query_param(self):
        self.client.force_authenticate(self.owner)
        other_child = _make_child(self.org, name="Данияр")
        ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=self.mother,
            role=ChildContact.Role.MOTHER,
        )
        ChildContact.objects.create(
            organization=self.org,
            child=other_child,
            parent_contact=self.grandmother,
            role=ChildContact.Role.GRANDMOTHER,
        )

        response = self.client.get(f"/api/v1/clients/child-contacts/?child={self.child.id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["parent_contact"], self.mother.id)

    def test_parent_with_two_children_visible_via_parent_contact_filter(self):
        self.client.force_authenticate(self.owner)
        second_child = _make_child(self.org, name="Данияр")
        ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=self.mother,
            role=ChildContact.Role.MOTHER,
        )
        ChildContact.objects.create(
            organization=self.org,
            child=second_child,
            parent_contact=self.mother,
            role=ChildContact.Role.MOTHER,
        )

        response = self.client.get(
            f"/api/v1/clients/child-contacts/?parent_contact={self.mother.id}"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        child_ids = {row["child"] for row in response.data["results"]}
        self.assertEqual(child_ids, {self.child.id, second_child.id})

    def test_teacher_cannot_attach_contact(self):
        self.client.force_authenticate(self.teacher)

        response = self.client.post(
            "/api/v1/clients/child-contacts/",
            {"child": str(self.child.id), "parent_contact": str(self.mother.id), "role": "mother"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_teacher_can_view_contacts_list(self):
        self.client.force_authenticate(self.teacher)

        response = self.client.get("/api/v1/clients/child-contacts/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)


@tag("tenant_isolation")
class ChildContactTenantIsolationTests(APITestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.org_b = Organization.objects.create(name="Другая студия", slug="another-studio")
        self.child_a = _make_child(self.org_a)
        self.child_b = _make_child(self.org_b, name="Чужой ребёнок")
        self.parent_b = ParentContact.objects.create(
            organization=self.org_b, full_name="Чужая мама"
        )
        self.link_b = ChildContact.objects.create(
            organization=self.org_b,
            child=self.child_b,
            parent_contact=self.parent_b,
            role=ChildContact.Role.MOTHER,
        )
        self.owner_a = User.objects.create_user(
            phone="+77010000001",
            full_name="Owner A",
            password="pass12345",
            organization=self.org_a,
            role=User.Role.OWNER,
        )
        self.client.force_authenticate(self.owner_a)

    def test_list_is_scoped_to_own_organization(self):
        response = self.client.get("/api/v1/clients/child-contacts/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["results"], [])

    def test_cannot_attach_another_organizations_parent_to_own_child(self):
        response = self.client.post(
            "/api/v1/clients/child-contacts/",
            {
                "child": str(self.child_a.id),
                "parent_contact": str(self.parent_b.id),
                "role": "mother",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("parent_contact", response.data)

    def test_cannot_attach_own_parent_to_another_organizations_child(self):
        own_parent = ParentContact.objects.create(organization=self.org_a, full_name="Своя мама")

        response = self.client.post(
            "/api/v1/clients/child-contacts/",
            {
                "child": str(self.child_b.id),
                "parent_contact": str(own_parent.id),
                "role": "mother",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("child", response.data)

    def test_cannot_detach_another_organizations_link(self):
        response = self.client.delete(f"/api/v1/clients/child-contacts/{self.link_b.id}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
