"""Пороги автостатусов читаются из настроек организации, а не хардкодятся."""

from django.test import TestCase

from domains.platform.tenants.models import Organization
from domains.platform.tenants.org_settings import (
    DEBT_OVERDUE_DAYS_THRESHOLD,
    DEFAULT_ORG_SETTINGS,
    get_org_setting,
)


class OrgSettingsHelperTests(TestCase):
    def test_get_org_setting_falls_back_to_default(self):
        org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.assertEqual(
            get_org_setting(org, DEBT_OVERDUE_DAYS_THRESHOLD),
            DEFAULT_ORG_SETTINGS[DEBT_OVERDUE_DAYS_THRESHOLD],
        )

    def test_get_org_setting_reads_stored_value(self):
        org = Organization.objects.create(
            name="True Ballet", slug="true-ballet", settings={DEBT_OVERDUE_DAYS_THRESHOLD: 15}
        )
        self.assertEqual(get_org_setting(org, DEBT_OVERDUE_DAYS_THRESHOLD), 15)
