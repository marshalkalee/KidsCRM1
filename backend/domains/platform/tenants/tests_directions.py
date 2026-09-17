"""
Направления: справочник и управление (ТЗ п. 3.1). Критерии приёмки:
- направление создаётся один раз и доступно в нескольких филиалах;
- архивированное направление не предлагается при создании новой группы
  (см. directions.get_selectable_directions), но остаётся в старых
  (Direction никуда не удаляется, просто is_active=False);
- изоляция между организациями (тег tenant_isolation).
"""

from django.contrib.auth import get_user_model
from django.test import TestCase, tag
from django.urls import reverse

from domains.platform.tenants.directions import get_selectable_directions
from domains.platform.tenants.forms import DirectionForm
from domains.platform.tenants.models import Branch, Direction, Organization

User = get_user_model()


class DirectionModelTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.branch_a = Branch.objects.create(organization=self.org, name="Филиал на Сатпаева")
        self.branch_b = Branch.objects.create(organization=self.org, name="Центральный филиал")

    def test_direction_created_once_is_available_in_several_branches(self):
        direction = Direction.objects.create(organization=self.org, name="Балет")
        direction.branches.add(self.branch_a, self.branch_b)

        self.assertEqual(direction.branches.count(), 2)
        self.assertIn(direction, self.branch_a.directions.all())
        self.assertIn(direction, self.branch_b.directions.all())

    def test_archiving_does_not_delete_direction(self):
        direction = Direction.objects.create(organization=self.org, name="Балет")
        direction.is_active = False
        direction.save(update_fields=["is_active"])

        # Не мягкое удаление (deleted_at) — обычный TenantManager её видит.
        self.assertTrue(Direction.objects.for_tenant(self.org).filter(pk=direction.pk).exists())

    def test_get_selectable_directions_excludes_archived(self):
        active = Direction.objects.create(organization=self.org, name="Балет")
        archived = Direction.objects.create(organization=self.org, name="Йога", is_active=False)

        selectable = get_selectable_directions(self.org)

        self.assertIn(active, selectable)
        self.assertNotIn(archived, selectable)

    def test_get_selectable_directions_filters_by_branch(self):
        direction = Direction.objects.create(organization=self.org, name="Балет")
        direction.branches.add(self.branch_a)

        self.assertIn(direction, get_selectable_directions(self.org, branch=self.branch_a))
        self.assertNotIn(direction, get_selectable_directions(self.org, branch=self.branch_b))


class DirectionFormTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.branch = Branch.objects.create(organization=self.org, name="Филиал")

    def test_rejects_invalid_hex_color(self):
        form = DirectionForm(
            data={"name": "Балет", "color": "purple", "age_min": "", "age_max": ""},
            organization=self.org,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("color", form.errors)

    def test_rejects_age_max_below_age_min(self):
        form = DirectionForm(
            data={"name": "Балет", "color": "#7C6FF7", "age_min": "10", "age_max": "5"},
            organization=self.org,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("age_max", form.errors)


class DirectionWebViewTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.branch_a = Branch.objects.create(organization=self.org, name="Филиал на Сатпаева")
        self.branch_b = Branch.objects.create(organization=self.org, name="Центральный филиал")
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

    def test_owner_creates_direction_available_in_two_branches(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("tenants_web:direction-create"),
            {
                "name": "Балет",
                "color": "#7C6FF7",
                "age_min": "5",
                "age_max": "12",
                "branches": [str(self.branch_a.pk), str(self.branch_b.pk)],
            },
        )
        self.assertEqual(response.status_code, 302)
        direction = Direction.objects.for_tenant(self.org).get(name="Балет")
        self.assertEqual(direction.branches.count(), 2)

    def test_teacher_cannot_create_direction(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("tenants_web:direction-create"))
        self.assertEqual(response.status_code, 403)

    def test_any_staff_can_view_direction_list(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("tenants_web:direction-list"))
        self.assertEqual(response.status_code, 200)

    def test_archiving_excludes_from_selectable_but_keeps_in_tenant_queryset(self):
        self.client.force_login(self.owner)
        direction = Direction.objects.create(organization=self.org, name="Балет")

        response = self.client.post(reverse("tenants_web:direction-archive", args=[direction.pk]))

        self.assertEqual(response.status_code, 302)
        direction.refresh_from_db()
        self.assertFalse(direction.is_active)
        self.assertNotIn(direction, get_selectable_directions(self.org))
        self.assertIn(direction, Direction.objects.for_tenant(self.org))

    def test_ajax_get_returns_form_fragment_not_full_page(self):
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("tenants_web:direction-create"), HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"<html", response.content)
        self.assertIn(b'name="name"', response.content)

    def test_ajax_post_valid_returns_json_success(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("tenants_web:direction-create"),
            {"name": "Гимнастика", "color": "#34D399"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"success": True})

    def test_ajax_post_invalid_returns_fragment_with_errors(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("tenants_web:direction-create"),
            {"name": "", "color": "#7C6FF7"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"kc-field--invalid", response.content)


@tag("tenant_isolation")
class DirectionTenantIsolationTests(TestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.org_b = Organization.objects.create(name="Другая студия", slug="another-studio")
        self.branch_b = Branch.objects.create(organization=self.org_b, name="Филиал B")
        self.direction_b = Direction.objects.create(organization=self.org_b, name="Балет Б")
        self.owner_a = User.objects.create_user(
            phone="+77010000001",
            full_name="Owner A",
            password="pass12345",
            organization=self.org_a,
            role=User.Role.OWNER,
        )
        self.client.force_login(self.owner_a)

    def test_cannot_edit_another_organizations_direction(self):
        response = self.client.get(
            reverse("tenants_web:direction-edit", args=[self.direction_b.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_cannot_archive_another_organizations_direction(self):
        response = self.client.post(
            reverse("tenants_web:direction-archive", args=[self.direction_b.pk])
        )
        self.assertEqual(response.status_code, 404)
        self.direction_b.refresh_from_db()
        self.assertTrue(self.direction_b.is_active)

    def test_direction_form_branch_choices_do_not_leak_other_organizations(self):
        form = DirectionForm(organization=self.org_a)
        self.assertNotIn(self.branch_b, form.fields["branches"].queryset)
