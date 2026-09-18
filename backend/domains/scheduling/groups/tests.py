from django.test import TestCase
from django.utils import timezone

from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group, GroupMembership


class GroupModelTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Test Org", slug="test-org")
        self.org2 = Organization.objects.create(name="Other Org", slug="other-org")
        self.branch = Branch.objects.create(organization=self.org, name="Главный")
        self.direction = Direction.objects.create(organization=self.org, name="Балет")
        self.owner = User.objects.create_user(
            phone="+77001111111", password="pass", organization=self.org, role="owner"
        )
        self.teacher = User.objects.create_user(
            phone="+77002222222", password="pass", organization=self.org, role="teacher"
        )
        self.teacher2 = User.objects.create_user(
            phone="+77003333333", password="pass", organization=self.org, role="teacher"
        )
        self.group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Балет — Младшая",
            capacity=12,
            age_min=5,
            age_max=8,
        )
        self.group.teachers.add(self.teacher)

    def test_group_created(self):
        self.assertEqual(Group.objects.for_tenant(self.org).count(), 1)
        self.assertEqual(self.group.capacity, 12)
        self.assertEqual(self.group.status, Group.Status.ACTIVE)

    def test_two_teachers(self):
        self.group.teachers.add(self.teacher2)
        self.assertEqual(self.group.teachers.count(), 2)

    def test_tenant_isolation(self):
        self.assertEqual(Group.objects.for_tenant(self.org2).count(), 0)

    def test_teacher_sees_own_groups_only(self):
        group2 = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Гимнастика",
            capacity=8,
        )
        group2.teachers.add(self.teacher2)
        qs = Group.objects.for_tenant(self.org).filter(teachers=self.teacher)
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first(), self.group)

    def test_soft_close(self):
        self.group.status = Group.Status.CLOSED
        self.group.save()
        active = Group.objects.for_tenant(self.org).filter(status=Group.Status.ACTIVE)
        self.assertEqual(active.count(), 0)

    def test_membership_history(self):
        from domains.people.clients.models import Child

        child = Child.objects.create(
            organization=self.org,
            full_name="Амина Серикова",
            birth_date="2019-03-12",
        )
        membership = GroupMembership.objects.create(
            organization=self.org,
            group=self.group,
            child=child,
            joined_at=timezone.now().date(),
        )
        self.assertTrue(membership.is_active)
        membership.left_at = timezone.now().date()
        membership.save()
        self.assertFalse(membership.is_active)

    def test_unique_active_membership(self):
        from django.db import IntegrityError

        from domains.people.clients.models import Child

        child = Child.objects.create(
            organization=self.org,
            full_name="Дана Абенова",
            birth_date="2017-07-22",
        )
        GroupMembership.objects.create(
            organization=self.org,
            group=self.group,
            child=child,
            joined_at=timezone.now().date(),
        )
        with self.assertRaises(IntegrityError):
            GroupMembership.objects.create(
                organization=self.org,
                group=self.group,
                child=child,
                joined_at=timezone.now().date(),
            )
