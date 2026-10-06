from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from domains.people.clients.models import Child
from domains.platform.tenants.models import Organization
from domains.platform.users.models import User
from domains.scheduling.schedule.models import Lesson


class LoadSeedTest(TestCase):
    """Быстрый контракт генератора; целевые 5000 детей проверяет load-run."""

    @patch("domains.platform.analytics.management.commands.seed_analytics.LEADS", 10)
    @patch("domains.platform.analytics.management.commands.seed_analytics.DAYS", 7)
    @patch("domains.platform.analytics.management.commands.seed_analytics.MANAGERS", 1)
    @patch("domains.platform.analytics.management.commands.seed_analytics.TEACHERS", 3)
    @patch("domains.platform.analytics.management.commands.seed_analytics.STAFF", 5)
    @patch("domains.platform.analytics.management.commands.seed_analytics.GROUP_SIZE", 5)
    @patch("domains.platform.analytics.management.commands.seed_analytics.CHILDREN", 20)
    @patch("domains.platform.analytics.management.commands.seed_analytics.BRANCHES", 2)
    def test_seed_creates_target_and_small_tenants(self):
        call_command(
            "seed_analytics",
            system_organizations=3,
            stdout=StringIO(),
        )

        target = Organization.objects.get(slug="analytics-volume")
        self.assertEqual(Organization.objects.count(), 3)
        self.assertEqual(Child.objects.for_tenant(target).count(), 20)
        self.assertEqual(User.objects.filter(organization=target).count(), 5)
        self.assertGreater(Lesson.objects.for_tenant(target).count(), 0)
        small = Organization.objects.exclude(pk=target.pk)
        self.assertEqual(Child.objects.filter(organization__in=small).count(), 20)
        self.assertEqual(Lesson.objects.filter(organization__in=small).count(), 4)
