"""seed_demo (TRU-89): наполняет организацию владельца, второй запуск ничего
не дублирует, без DEBUG не запускается."""

import io

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from domains.people.clients.models import Child
from domains.platform.tenants.models import Organization
from domains.scheduling.groups.models import Group

User = get_user_model()


class SeedDemoTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Demo", slug="demo")
        User.objects.create_user(
            phone="+77011234567",
            full_name="Owner",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )

    @override_settings(DEBUG=True)
    def test_seeds_once(self):
        call_command("seed_demo", children=20, stdout=io.StringIO())
        children = Child.objects.for_tenant(self.org).count()
        groups = Group.objects.for_tenant(self.org).count()

        call_command("seed_demo", children=20, stdout=io.StringIO())

        self.assertGreaterEqual(children, 20)
        self.assertGreater(groups, 0)
        self.assertEqual(Child.objects.for_tenant(self.org).count(), children)

    @override_settings(DEBUG=False)
    def test_refuses_without_debug(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo", children=5)
