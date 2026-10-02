"""
Мастер онбординга (ТЗ п. 10.4): маршрут, пропуск и возобновление с того же
места, прогресс на главной, и главное — мастер не пишет данные своим путём.
"""

import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase

from domains.money.subscriptions.subscription_types import create_type
from domains.people.clients.models import ImportJob
from domains.platform.tenants import onboarding
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.tenants.onboarding import Step
from domains.platform.tenants.org_settings import SUBSCRIPTION_ENDING_LESSONS_THRESHOLD
from domains.scheduling.groups.models import Group

User = get_user_model()


def _owner(org, phone="+77010000001", role=User.Role.OWNER):
    return User.objects.create_user(
        phone=phone, full_name="Owner", password="pass12345", organization=org, role=role
    )


class OnboardingStateTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Новый центр", slug="new-center")

    def test_new_organization_starts_at_the_first_step(self):
        self.assertEqual(onboarding.current_step(self.org), Step.ORGANIZATION)
        self.assertEqual(onboarding.progress(self.org).done, 0)

    def test_steps_are_done_by_data_not_by_flags(self):
        # Филиал, заведённый в обычных настройках мимо мастера, — тоже шаг пройден.
        onboarding.confirm_organization(self.org)
        Branch.objects.create(organization=self.org, name="Центральный")

        self.assertEqual(onboarding.current_step(self.org), Step.DIRECTIONS)

    def test_skipped_step_is_passed_over_and_resumes_at_the_next_one(self):
        onboarding.confirm_organization(self.org)
        onboarding.skip_step(self.org, Step.BRANCH)

        self.assertEqual(onboarding.current_step(self.org), Step.DIRECTIONS)
        branch = next(s for s in onboarding.get_steps(self.org) if s.key == Step.BRANCH)
        self.assertEqual(branch.status, "skipped")

    def test_skipped_step_counts_as_done_once_data_appears(self):
        onboarding.skip_step(self.org, Step.BRANCH)
        Branch.objects.create(organization=self.org, name="Центральный")

        branch = next(s for s in onboarding.get_steps(self.org) if s.key == Step.BRANCH)
        self.assertEqual(branch.status, "done")

    def test_saving_organization_settings_screen_confirms_organization_step(self):
        self.org.settings = {SUBSCRIPTION_ENDING_LESSONS_THRESHOLD: 2}
        self.org.save()

        self.assertEqual(onboarding.current_step(self.org), Step.BRANCH)

    def test_onboarding_state_does_not_clobber_thresholds(self):
        self.org.settings = {SUBSCRIPTION_ENDING_LESSONS_THRESHOLD: 2}
        self.org.save()

        onboarding.skip_step(self.org, Step.BRANCH)

        self.org.refresh_from_db()
        self.assertEqual(self.org.settings[SUBSCRIPTION_ENDING_LESSONS_THRESHOLD], 2)

    def test_all_data_steps(self):
        owner = _owner(self.org)
        onboarding.confirm_organization(self.org)
        branch = Branch.objects.create(organization=self.org, name="Центральный")
        direction = Direction.objects.create(organization=self.org, name="Балет")
        create_type(self.org, name="8 занятий", price=20000, quota_sessions=8, duration_days=30)
        Group.objects.create(
            organization=self.org, branch=branch, direction=direction, name="Мини", capacity=10
        )
        self.assertEqual(onboarding.current_step(self.org), Step.IMPORT)

        ImportJob.objects.create(
            organization=self.org,
            created_by=owner,
            job_type=ImportJob.JobType.EXECUTE,
            status=ImportJob.Status.DONE,
            total_rows=0,
            rows_payload=[],
        )

        self.assertIsNone(onboarding.current_step(self.org))
        self.assertIsNone(onboarding.progress(self.org))

    def test_rolled_back_import_does_not_count(self):
        owner = _owner(self.org)
        ImportJob.objects.create(
            organization=self.org,
            created_by=owner,
            job_type=ImportJob.JobType.EXECUTE,
            status=ImportJob.Status.DONE,
            total_rows=0,
            rows_payload=[],
            rolled_back_at=datetime.datetime(2026, 9, 1, tzinfo=datetime.UTC),
        )

        step = next(s for s in onboarding.get_steps(self.org) if s.key == Step.IMPORT)
        self.assertFalse(step.done)

    def test_finished_onboarding_hides_progress(self):
        onboarding.finish(self.org)

        self.assertIsNone(onboarding.progress(self.org))
