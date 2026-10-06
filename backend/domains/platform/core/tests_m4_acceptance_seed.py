from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from domains.people.clients.models import Child, ChildContact, ContactPhone, ParentContact
from domains.people.portal.access import children_for_phone
from domains.people.portal.models import ParentAccount
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.schedule.models import Lesson

from .management.commands.seed_m4_acceptance import PROFILES


@override_settings(DEBUG=True)
class M4AcceptanceSeedTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        branch = Branch.objects.create(organization=self.org, name="Главный")
        direction = Direction.objects.create(organization=self.org, name="Балет")
        for number in range(3):
            group = Group.objects.create(
                organization=self.org,
                branch=branch,
                direction=direction,
                name=f"Группа {number + 1}",
                capacity=12,
            )
            child = Child.objects.create(
                organization=self.org,
                full_name=f"Ребёнок {number + 1}",
                birth_date=timezone.localdate().replace(year=timezone.localdate().year - 9),
            )
            GroupMembership.objects.create(
                organization=self.org,
                group=group,
                child=child,
                joined_at=timezone.localdate(),
            )
            Lesson.objects.create(
                organization=self.org,
                group=group,
                starts_at=timezone.now() + timedelta(days=number + 1),
                ends_at=timezone.now() + timedelta(days=number + 1, hours=1),
            )

    def test_command_is_idempotent_and_profiles_see_only_linked_children(self):
        call_command("seed_m4_acceptance", stdout=StringIO())
        call_command("seed_m4_acceptance", stdout=StringIO())

        self.assertEqual(
            ParentAccount.objects.filter(phone__in=[p[0] for p in PROFILES]).count(), 3
        )
        self.assertEqual(
            ParentContact.objects.filter(whatsapp__in=[p[0] for p in PROFILES]).count(), 3
        )
        self.assertEqual(
            ContactPhone.objects.filter(number__in=[p[0] for p in PROFILES]).count(), 3
        )
        self.assertEqual(
            ChildContact.objects.filter(
                parent_contact__whatsapp__in=[p[0] for p in PROFILES]
            ).count(),
            3,
        )
        for phone, _name, _language in PROFILES:
            self.assertEqual(children_for_phone(phone).count(), 1)
