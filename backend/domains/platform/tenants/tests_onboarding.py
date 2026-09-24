"""
Мастер онбординга (ТЗ п. 10.4): маршрут, пропуск и возобновление с того же
места, прогресс на главной, и главное — мастер не пишет данные своим путём.
"""

import datetime

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

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


class OnboardingViewsTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Новый центр", slug="new-center")
        self.owner = _owner(self.org)
        self.client.force_login(self.owner)

    def test_start_redirects_to_current_step(self):
        onboarding.confirm_organization(self.org)

        response = self.client.get(reverse("tenants_web:onboarding"))

        self.assertRedirects(response, reverse("tenants_web:onboarding-step", args=[Step.BRANCH]))

    def test_organization_step_saves_through_the_settings_form(self):
        response = self.client.post(
            reverse("tenants_web:onboarding-step", args=[Step.ORGANIZATION]),
            {
                "name": "Балетная студия",
                "timezone": "Asia/Almaty",
                "subscription_ending_lessons_threshold": 2,
                "subscription_ending_days_threshold": 7,
                "debt_overdue_days_threshold": 5,
                "group_underfilled_percent_threshold": 50,
            },
        )

        self.assertRedirects(response, reverse("tenants_web:onboarding-step", args=[Step.BRANCH]))
        self.org.refresh_from_db()
        self.assertEqual(self.org.name, "Балетная студия")
        self.assertEqual(self.org.settings[SUBSCRIPTION_ENDING_LESSONS_THRESHOLD], 2)

    def test_organization_step_is_prefilled_with_defaults(self):
        response = self.client.get(reverse("tenants_web:onboarding-step", args=[Step.ORGANIZATION]))

        self.assertEqual(response.context["form"]["timezone"].value(), "Asia/Almaty")
        self.assertEqual(
            response.context["form"]["subscription_ending_lessons_threshold"].value(), 3
        )

    def test_branch_step_opens_the_regular_branch_form(self):
        response = self.client.get(reverse("tenants_web:onboarding-step", args=[Step.BRANCH]))

        # Та же вьюха, что на экране филиалов — один путь записи.
        self.assertContains(response, reverse("tenants_web:branch-create"))

    def test_groups_step_opens_the_regular_group_form_and_names_missing_prerequisites(self):
        response = self.client.get(reverse("tenants_web:onboarding-step", args=[Step.GROUPS]))

        self.assertContains(response, reverse("scheduling_web:group-create"))
        self.assertEqual(response.context["missing_for_groups"], ["Филиал", "Направления"])

    def test_subscription_types_step_is_a_skippable_placeholder_for_now(self):
        response = self.client.get(
            reverse("tenants_web:onboarding-step", args=[Step.SUBSCRIPTION_TYPES])
        )

        self.assertIsNone(response.context["create_url"])
        self.assertContains(
            response, reverse("tenants_web:onboarding-skip", args=[Step.SUBSCRIPTION_TYPES])
        )

    def test_import_step_links_to_the_regular_import(self):
        response = self.client.get(reverse("tenants_web:onboarding-step", args=[Step.IMPORT]))

        self.assertContains(response, reverse("clients_web:child-import-upload"))
        self.assertContains(response, "Пока пропущу")

    def test_skip_moves_on_and_wizard_resumes_from_the_same_place(self):
        onboarding.confirm_organization(self.org)

        response = self.client.post(reverse("tenants_web:onboarding-skip", args=[Step.BRANCH]))
        self.assertRedirects(
            response, reverse("tenants_web:onboarding-step", args=[Step.DIRECTIONS])
        )

        # Ушли с сайта и вернулись — мастер там же, где остановились.
        response = self.client.get(reverse("tenants_web:onboarding"))
        self.assertRedirects(
            response, reverse("tenants_web:onboarding-step", args=[Step.DIRECTIONS])
        )

    def test_when_everything_is_done_or_skipped_the_done_page_lists_skipped_steps(self):
        for step in onboarding.STEP_ORDER:
            onboarding.skip_step(self.org, step)

        response = self.client.get(reverse("tenants_web:onboarding"))
        self.assertRedirects(response, reverse("tenants_web:onboarding-done"))

        response = self.client.get(reverse("tenants_web:onboarding-done"))
        self.assertEqual(len(response.context["skipped_steps"]), 6)

    def test_finish_hides_the_home_card(self):
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, "Продолжить настройку")

        self.client.post(reverse("tenants_web:onboarding-finish"))

        response = self.client.get(reverse("core:home"))
        self.assertNotContains(response, "Продолжить настройку")

    def test_home_card_shows_progress(self):
        onboarding.confirm_organization(self.org)
        Branch.objects.create(organization=self.org, name="Центральный")

        response = self.client.get(reverse("core:home"))

        self.assertContains(response, "2 / 6")

    def test_unknown_step_is_404(self):
        response = self.client.get(reverse("tenants_web:onboarding-step", args=["payments"]))

        self.assertEqual(response.status_code, 404)

    def test_wizard_is_owner_only_and_home_card_hidden_for_others(self):
        admin = _owner(self.org, phone="+77010000002", role=User.Role.ADMIN)
        self.client.force_login(admin)

        self.assertEqual(self.client.get(reverse("tenants_web:onboarding")).status_code, 403)
        self.assertNotContains(self.client.get(reverse("core:home")), "Продолжить настройку")


class SignupTests(TestCase):
    """Регистрация центра с сайта — тот же путь записи, что у API."""

    def setUp(self):
        cache.clear()  # лимит запросов на регистрацию считается в кэше

    def _signup(self, **overrides):
        data = {
            "org_name": "Балетная студия",
            "full_name": "Айгерим Серикова",
            "phone": "8 701 555 66 77",
            "password": "StrongPass-2026",
        }
        data.update(overrides)
        return self.client.post(reverse("core:signup"), data)

    def test_signup_creates_organization_and_owner_logs_in_and_opens_wizard(self):
        response = self._signup()

        self.assertRedirects(
            response,
            reverse("tenants_web:onboarding"),
            target_status_code=302,
        )
        owner = User.objects.get(phone="+77015556677")
        self.assertEqual(owner.role, User.Role.OWNER)
        self.assertEqual(owner.organization.name, "Балетная студия")
        self.assertEqual(self.client.session["_auth_user_id"], str(owner.pk))

    def test_duplicate_phone_is_a_form_error_not_a_crash(self):
        self._signup()
        self.client.logout()

        response = self._signup(org_name="Другой центр", phone="+7 701 555-66-77")

        self.assertEqual(response.status_code, 200)
        self.assertIn("phone", response.context["errors"])
        self.assertEqual(Organization.objects.count(), 1)

    def test_weak_password_is_rejected(self):
        response = self._signup(password="123")

        self.assertIn("password", response.context["errors"])
        self.assertFalse(Organization.objects.exists())

    def test_can_log_in_typing_phone_the_usual_way(self):
        self._signup()
        self.client.logout()

        response = self.client.post(
            reverse("core:login"), {"phone": "8 701 555 66 77", "password": "StrongPass-2026"}
        )

        self.assertRedirects(response, reverse("core:home"))

    def test_login_page_links_to_signup(self):
        response = self.client.get(reverse("core:login"))

        self.assertContains(response, reverse("core:signup"))
