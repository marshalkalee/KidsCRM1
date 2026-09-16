"""
Веб-экраны "Настройки организации, филиалы и залы" (серверный рендеринг,
сессия — см. web_views.py). Критерии приёмки тикета:
- владелец создаёт филиал/зал без обращения к разработчику;
- смена часового пояса организации меняет отображение уже существующих
  занятий/оплат (здесь — общий механизм kc_datetime, конкретных
  занятий/оплат в этой ветке ещё нет);
- пороги автостатусов читаются из настроек, не хардкодятся;
- архивированный филиал пропадает из выбора, но история доступна;
- изоляция между организациями (тег tenant_isolation).
"""

from datetime import UTC, datetime

from django.contrib.auth import get_user_model
from django.test import TestCase, tag
from django.urls import reverse

from domains.platform.core.context_processors import branches
from domains.platform.core.templatetags.kc_format import kc_datetime
from domains.platform.tenants.models import Branch, Organization, Room
from domains.platform.tenants.org_settings import (
    DEBT_OVERDUE_DAYS_THRESHOLD,
    DEFAULT_ORG_SETTINGS,
    get_org_setting,
)

User = get_user_model()


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


class OrganizationSettingsViewTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(
            name="True Ballet", slug="true-ballet", timezone="Asia/Almaty"
        )
        self.owner = User.objects.create_user(
            phone="+77010000001",
            full_name="Owner",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.manager = User.objects.create_user(
            phone="+77010000002",
            full_name="Manager",
            password="pass12345",
            organization=self.org,
            role=User.Role.MANAGER,
        )

    def test_non_owner_is_forbidden(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("tenants_web:organization-settings"))
        self.assertEqual(response.status_code, 403)

    def test_owner_can_view_settings_page(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("tenants_web:organization-settings"))
        self.assertEqual(response.status_code, 200)

    def test_owner_updates_thresholds_not_hardcoded(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("tenants_web:organization-settings"),
            {
                "name": "True Ballet",
                "timezone": "Asia/Almaty",
                "subscription_ending_lessons_threshold": 5,
                "subscription_ending_days_threshold": 10,
                "debt_overdue_days_threshold": 3,
                "group_underfilled_percent_threshold": 40,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.org.refresh_from_db()
        self.assertEqual(get_org_setting(self.org, "debt_overdue_days_threshold"), 3)
        self.assertEqual(get_org_setting(self.org, "group_underfilled_percent_threshold"), 40)

    def test_changing_timezone_changes_datetime_rendering(self):
        """
        Критерий приёмки: смена часового пояса организации корректно меняет
        отображение уже существующих занятий/оплат. Конкретных Lesson/
        Payment моделей в этой ветке ещё нет — проверяем сам механизм
        (kc_datetime всегда читает organization.timezone на момент рендера,
        см. templatetags/kc_format.py), которым все будущие экраны обязаны
        пользоваться вместо своего форматирования.
        """
        value = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        user = type("FakeUser", (), {"organization": self.org})()
        request = type("FakeRequest", (), {"user": user})()

        before = kc_datetime({"request": request}, value)

        self.client.force_login(self.owner)
        self.client.post(
            reverse("tenants_web:organization-settings"),
            {
                "name": "True Ballet",
                "timezone": "UTC",
                "subscription_ending_lessons_threshold": 3,
                "subscription_ending_days_threshold": 7,
                "debt_overdue_days_threshold": 5,
                "group_underfilled_percent_threshold": 50,
            },
        )
        self.org.refresh_from_db()
        user.organization = self.org
        after = kc_datetime({"request": request}, value)

        self.assertEqual(before, "15.01.2026 17:00")  # Asia/Almaty, UTC+5
        self.assertEqual(after, "15.01.2026 12:00")  # UTC
        self.assertNotEqual(before, after)


class BranchWebViewTests(TestCase):
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
            phone="+77010000003",
            full_name="Teacher",
            password="pass12345",
            organization=self.org,
            role=User.Role.TEACHER,
        )

    def test_owner_creates_second_branch_without_developer(self):
        self.client.force_login(self.owner)
        Branch.objects.create(organization=self.org, name="Филиал на Сатпаева")

        response = self.client.post(
            reverse("tenants_web:branch-create"),
            {
                "name": "Центральный филиал",
                "address": "ул. Абая, 1",
                "phone": "+77011234567",
                "mon_closed": "",
                "mon_open": "09:00",
                "mon_close": "20:00",
                "tue_closed": "",
                "tue_open": "09:00",
                "tue_close": "20:00",
                "wed_closed": "",
                "wed_open": "09:00",
                "wed_close": "20:00",
                "thu_closed": "",
                "thu_open": "09:00",
                "thu_close": "20:00",
                "fri_closed": "",
                "fri_open": "09:00",
                "fri_close": "20:00",
                "sat_closed": "on",
                "sun_closed": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Branch.objects.for_tenant(self.org).count(), 2)
        branch = Branch.objects.for_tenant(self.org).get(name="Центральный филиал")
        self.assertEqual(
            branch.working_hours["mon"], {"closed": False, "open": "09:00", "close": "20:00"}
        )
        self.assertEqual(branch.working_hours["sun"], {"closed": True})

        # И зал в новом филиале — та же логика, тоже без похода к разработчику.
        room_response = self.client.post(
            reverse("tenants_web:room-create", args=[branch.pk]),
            {"name": "Большой зал", "capacity": 20},
        )
        self.assertEqual(room_response.status_code, 302)
        self.assertEqual(Room.objects.for_tenant(self.org).filter(branch=branch).count(), 1)

    def test_teacher_cannot_create_branch(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("tenants_web:branch-create"))
        self.assertEqual(response.status_code, 403)

    def test_ajax_get_returns_form_fragment_not_full_page(self):
        """
        Модалка создания/редактирования (см. static/site/js/components/
        form-modal.js) грузит форму этим запросом и вставляет ответ прямо
        в .modal-body — там не должно быть <html>/сайдбара, только поля.
        """
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("tenants_web:branch-create"), HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"<html", response.content)
        self.assertIn(b'name="name"', response.content)

    def test_ajax_post_valid_returns_json_success(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("tenants_web:branch-create"),
            {"name": "Филиал через модалку"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"success": True})
        self.assertTrue(
            Branch.objects.for_tenant(self.org).filter(name="Филиал через модалку").exists()
        )

    def test_ajax_post_invalid_returns_fragment_with_errors_not_redirect(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("tenants_web:branch-create"),
            {"name": ""},  # обязательное поле пустое
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"kc-field--invalid", response.content)

    def test_archiving_branch_toggles_is_active(self):
        self.client.force_login(self.owner)
        branch = Branch.objects.create(organization=self.org, name="Филиал")

        response = self.client.post(reverse("tenants_web:branch-archive", args=[branch.pk]))

        self.assertEqual(response.status_code, 302)
        branch.refresh_from_db()
        self.assertFalse(branch.is_active)

    def test_archived_branch_disappears_from_switcher_but_stays_in_history(self):
        self.client.force_login(self.owner)
        branch = Branch.objects.create(organization=self.org, name="Филиал")
        self.client.post(reverse("tenants_web:branch-archive", args=[branch.pk]))
        branch.refresh_from_db()
        self.assertFalse(branch.is_active)

        request = type("FakeRequest", (), {"user": self.owner, "session": {}})()
        context = branches(request)
        self.assertNotIn(branch, context["kc_branches"])

        # Историческая доступность — обычный for_tenant() архивацию не фильтрует.
        self.assertIn(branch, list(Branch.objects.for_tenant(self.org)))

    def test_room_soft_delete_removes_from_tenant_queryset(self):
        self.client.force_login(self.owner)
        branch = Branch.objects.create(organization=self.org, name="Филиал")
        room = Room.objects.create(branch=branch, name="Зал")

        response = self.client.post(reverse("tenants_web:room-delete", args=[branch.pk, room.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Room.objects.for_tenant(self.org).filter(pk=room.pk).exists())


@tag("tenant_isolation")
class BranchRoomWebTenantIsolationTests(TestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.org_b = Organization.objects.create(name="Другая студия", slug="another-studio")
        self.branch_a = Branch.objects.create(organization=self.org_a, name="Филиал A")
        self.branch_b = Branch.objects.create(organization=self.org_b, name="Филиал B")
        self.room_b = Room.objects.create(branch=self.branch_b, name="Зал B")
        self.owner_a = User.objects.create_user(
            phone="+77010000001",
            full_name="Owner A",
            password="pass12345",
            organization=self.org_a,
            role=User.Role.OWNER,
        )
        self.client.force_login(self.owner_a)

    def test_cannot_edit_another_organizations_branch(self):
        response = self.client.get(reverse("tenants_web:branch-edit", args=[self.branch_b.pk]))
        self.assertEqual(response.status_code, 404)

    def test_cannot_archive_another_organizations_branch(self):
        response = self.client.post(reverse("tenants_web:branch-archive", args=[self.branch_b.pk]))
        self.assertEqual(response.status_code, 404)
        self.branch_b.refresh_from_db()
        self.assertTrue(self.branch_b.is_active)

    def test_cannot_view_rooms_of_another_organizations_branch(self):
        response = self.client.get(reverse("tenants_web:room-list", args=[self.branch_b.pk]))
        self.assertEqual(response.status_code, 404)

    def test_cannot_delete_room_of_another_organizations_branch(self):
        response = self.client.post(
            reverse("tenants_web:room-delete", args=[self.branch_b.pk, self.room_b.pk])
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Room.objects.filter(pk=self.room_b.pk).exists())
