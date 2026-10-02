"""
Направления: справочник и управление (ТЗ п. 3.1). Критерии приёмки:
- направление создаётся один раз и доступно в нескольких филиалах;
- архивированное направление не предлагается при создании новой группы
  (см. directions.get_selectable_directions), но остаётся в старых
  (Direction никуда не удаляется, просто is_active=False);
- изоляция между организациями (тег tenant_isolation).
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

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
