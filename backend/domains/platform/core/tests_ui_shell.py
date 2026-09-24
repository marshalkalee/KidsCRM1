from datetime import UTC, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, tag
from django.urls import reverse

from domains.platform.core.templatetags.kc_format import kc_datetime, kc_money
from domains.platform.tenants.models import Branch, Organization

User = get_user_model()


class RoleRequiredDecoratorTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
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
        self.no_org_user = User.objects.create_user(
            phone="+77010000003",
            full_name="No Org",
            password="pass12345",
        )

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("core:login"), response.url)

    def test_authenticated_without_organization_is_forbidden(self):
        self.client.force_login(self.no_org_user)
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 403)

    def test_authenticated_with_organization_can_open_home(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)

    def test_role_restricted_view_blocks_wrong_role(self):
        from django.core.exceptions import PermissionDenied
        from django.http import HttpResponse
        from django.test import RequestFactory

        from domains.platform.core.decorators import role_required

        @role_required(User.Role.OWNER)
        def owner_only_view(request):
            return HttpResponse("ok")

        request = RequestFactory().get("/owner-only/")
        request.user = self.teacher
        # Вызов view-функции напрямую (не через self.client) минует
        # middleware, который в обычном запросе превращает PermissionDenied
        # в HTTP 403 — поэтому здесь проверяем само исключение.
        with self.assertRaises(PermissionDenied):
            owner_only_view(request)

    def test_role_restricted_view_allows_matching_role(self):
        from django.http import HttpResponse
        from django.test import RequestFactory

        from domains.platform.core.decorators import role_required

        @role_required(User.Role.OWNER)
        def owner_only_view(request):
            return HttpResponse("ok")

        request = RequestFactory().get("/owner-only/")
        request.user = self.owner
        response = owner_only_view(request)
        self.assertEqual(response.status_code, 200)


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.user = User.objects.create_user(
            phone="+77010000001",
            full_name="Owner",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )

    def test_login_with_correct_credentials_succeeds(self):
        response = self.client.post(
            reverse("core:login"), {"phone": "+77010000001", "password": "pass12345"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("core:home"))

    def test_login_with_wrong_password_shows_error(self):
        response = self.client.post(
            reverse("core:login"), {"phone": "+77010000001", "password": "wrong"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "login.error")

    def test_already_logged_in_get_redirects_home(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("core:login"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("core:home"))

    def test_logout_clears_session(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("core:logout"))
        self.assertEqual(response.status_code, 302)
        # После логаута защищённая страница снова редиректит на login.
        home_response = self.client.get(reverse("core:home"))
        self.assertEqual(home_response.status_code, 302)


@tag("tenant_isolation")
class BranchSwitcherTests(TestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.org_b = Organization.objects.create(name="Другая студия", slug="another-studio")
        self.branch_a = Branch.objects.create(organization=self.org_a, name="Филиал A")
        self.branch_b = Branch.objects.create(organization=self.org_b, name="Филиал B")
        self.user_a = User.objects.create_user(
            phone="+77010000001",
            full_name="Owner A",
            password="pass12345",
            organization=self.org_a,
            role=User.Role.OWNER,
        )
        self.client.force_login(self.user_a)

    def test_switch_to_own_branch_updates_session(self):
        self.client.post(reverse("core:switch-branch"), {"branch_id": str(self.branch_a.id)})
        self.assertEqual(self.client.session.get("active_branch_id"), str(self.branch_a.id))

    def test_cannot_switch_to_another_organizations_branch(self):
        self.client.post(reverse("core:switch-branch"), {"branch_id": str(self.branch_b.id)})
        self.assertNotEqual(self.client.session.get("active_branch_id"), str(self.branch_b.id))


class LanguageSwitcherTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.user = User.objects.create_user(
            phone="+77010000001",
            full_name="Owner",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.client.force_login(self.user)

    def test_switch_to_known_language_updates_session(self):
        self.client.post(reverse("core:switch-language"), {"lang": "kk"})
        self.assertEqual(self.client.session.get("lang"), "kk")

    def test_unknown_language_is_ignored(self):
        self.client.post(reverse("core:switch-language"), {"lang": "fr"})
        self.assertNotIn("lang", self.client.session)

    def test_default_language_is_russian_in_html_lang_attribute(self):
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, '<html lang="ru">')

    def test_switched_language_reflected_in_html_lang_attribute(self):
        self.client.post(reverse("core:switch-language"), {"lang": "en"})
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, '<html lang="en">')


class FormatFiltersTests(TestCase):
    def test_kc_money_delegates_to_format_tenge(self):
        self.assertEqual(kc_money(Decimal("12500")), "12 500 ₸")

    def test_kc_datetime_converts_to_organization_timezone(self):
        org = Organization.objects.create(
            name="True Ballet", slug="true-ballet", timezone="Asia/Almaty"
        )
        user = type("FakeUser", (), {"organization": org})()
        request = type("FakeRequest", (), {"user": user})()
        # 12:00 UTC = 17:00 в Asia/Almaty (UTC+5).
        value = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        result = kc_datetime({"request": request}, value)
        self.assertEqual(result, "15.01.2026 17:00")
