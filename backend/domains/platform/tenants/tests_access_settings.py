"""TRU-153: доступ сотрудников внутри роли. Каждое скрываемое поле проверяется
запросом к API токеном роли — и в ответе, и в выгрузке Excel; по умолчанию
поведение прежнее."""

import io
from datetime import timedelta

import openpyxl
from rest_framework.test import APITestCase

from domains.money.payments.services import record_payment
from domains.money.subscriptions.models import Subscription
from domains.money.subscriptions.subscription_types import create_type
from domains.people.clients.models import Child, ChildContact, ContactPhone, ParentContact
from domains.platform.core.audit import AuditLog
from domains.platform.core.utils import today_for_org
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User

ACCESS_URL = "/api/v1/organization/access/"
PHONE = "+77071112233"


def rows(response):
    data = response.data
    return data["results"] if isinstance(data, dict) else data


class AccessSettingsTests(APITestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.branch = Branch.objects.create(organization=self.org, name="Абая")
        self.other_branch = Branch.objects.create(organization=self.org, name="Орбита")
        ballet = Direction.objects.create(organization=self.org, name="Балет")
        sub_type = create_type(
            self.org,
            name="8 занятий",
            price=30000,
            quota_sessions=8,
            duration_days=30,
            directions=[ballet],
        )
        self.owner, self.admin, self.teacher = (
            User.objects.create_user(
                phone=f"+7701000000{i}",
                password="x",
                full_name=role.label,
                organization=self.org,
                role=role,
            )
            for i, role in enumerate((User.Role.OWNER, User.Role.ADMIN, User.Role.TEACHER), 1)
        )
        self.admin.branches.add(self.branch)
        today = today_for_org(self.org)
        self.child = Child.objects.create(
            organization=self.org, full_name="Алия Долгова", birth_date=today - timedelta(days=3000)
        )
        parent = ParentContact.objects.create(
            organization=self.org, full_name="Мама Алии", whatsapp=PHONE
        )
        ContactPhone.objects.create(organization=self.org, parent_contact=parent, number=PHONE)
        ChildContact.objects.create(
            organization=self.org, child=self.child, parent_contact=parent, is_payer=True
        )
        self.subscription = Subscription.objects.create(
            organization=self.org,
            child=self.child,
            subscription_type_version=sub_type.versions.latest(),
            direction=ballet,
            branch=self.branch,
            starts_on=today - timedelta(days=1),
            ends_on=today + timedelta(days=29),
            list_price=30000,
            price=30000,
        )
        record_payment(
            actor=self.admin, subscription=self.subscription, amount=10000, method="cash"
        )

    def as_user(self, user):
        self.client.force_authenticate(user)
        return self.client

    def set_access(self, **values):
        response = self.as_user(self.owner).put(ACCESS_URL, values, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def permissions(self, user):
        return self.as_user(user).get("/api/v1/users/auth/me/").data["permissions"]

    def export_header(self, user):
        response = self.as_user(user).get("/api/v1/subscriptions/debtors/export/")
        self.assertEqual(response.status_code, 200)
        sheet = openpyxl.load_workbook(io.BytesIO(response.content)).active
        return [cell.value for cell in sheet[1]]

    # --- настройка ---

    def test_defaults_keep_previous_behaviour(self):
        self.assertEqual(
            self.as_user(self.owner).get(ACCESS_URL).data,
            {
                "teacher_sees_parent_phones": False,
                "teacher_sees_finances": False,
                "admin_sees_org_summary": False,
            },
        )
        teacher = self.permissions(self.teacher)
        self.assertFalse(teacher["can_view_phone"])
        self.assertFalse(teacher["can_view_client_money"])
        self.assertFalse(self.permissions(self.admin)["can_view_analytics"])

    def test_only_owner_manages_access(self):
        for user in (self.admin, self.teacher):
            client = self.as_user(user)
            self.assertEqual(client.get(ACCESS_URL).status_code, 403)
            self.assertEqual(
                client.put(ACCESS_URL, {"teacher_sees_finances": True}, format="json").status_code,
                403,
            )

    def test_partial_update_and_validation(self):
        data = self.set_access(teacher_sees_finances=True).data
        self.assertTrue(data["teacher_sees_finances"])
        self.assertFalse(data["teacher_sees_parent_phones"])
        client = self.as_user(self.owner)
        bad = client.put(ACCESS_URL, {"teacher_sees_finances": "yes"}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertIn("teacher_sees_finances", bad.data)
        unknown = client.put(ACCESS_URL, {"teacher_is_owner": True}, format="json")
        self.assertEqual(unknown.status_code, 400)
        self.org.refresh_from_db()
        self.assertTrue(self.org.settings["teacher_sees_finances"])
        self.assertNotIn("teacher_is_owner", self.org.settings)

    def test_change_is_audited_and_noop_is_not(self):
        self.set_access(teacher_sees_parent_phones=True, admin_sees_org_summary=False)
        log = AuditLog.objects.get(organization=self.org, actor=self.owner)
        self.assertEqual(log.action, AuditLog.Action.UPDATE)
        self.assertEqual(log.before, {"teacher_sees_parent_phones": False})
        self.assertEqual(log.after, {"teacher_sees_parent_phones": True})
        self.set_access(teacher_sees_parent_phones=True)
        self.assertEqual(AuditLog.objects.filter(actor=self.owner).count(), 1)

    def test_org_settings_form_does_not_reset_access(self):
        self.set_access(teacher_sees_finances=True)
        self.as_user(self.owner).put(
            "/api/v1/organization/settings/",
            {
                "name": "True Ballet",
                "timezone": "Asia/Almaty",
                "subscription_ending_lessons_threshold": 2,
                "subscription_ending_days_threshold": 7,
                "debt_overdue_days_threshold": 5,
                "group_underfilled_percent_threshold": 50,
            },
            format="json",
        )
        self.org.refresh_from_db()
        self.assertTrue(self.org.settings["teacher_sees_finances"])

    # --- телефоны родителей преподавателю ---

    def test_teacher_phones_hidden_by_default_everywhere(self):
        client = self.as_user(self.teacher)
        parent = rows(client.get("/api/v1/clients/parents/"))[0]
        self.assertNotIn("phones", parent)
        self.assertNotIn("whatsapp", parent)
        contact = rows(client.get("/api/v1/clients/child-contacts/", {"child": self.child.id}))[0]
        self.assertNotIn("parent_contact_phones", contact)
        self.assertNotIn(PHONE, str(client.get("/api/v1/clients/parents/").data))

    def test_teacher_sees_phones_when_allowed(self):
        self.set_access(teacher_sees_parent_phones=True)
        self.assertTrue(self.permissions(self.teacher)["can_view_phone"])
        parent = rows(self.as_user(self.teacher).get("/api/v1/clients/parents/"))[0]
        self.assertEqual([p["number"] for p in parent["phones"]], [PHONE])

    # --- деньги преподавателю ---

    def test_teacher_money_closed_by_default(self):
        client = self.as_user(self.teacher)
        for url in (
            "/api/v1/subscriptions/debtors/",
            "/api/v1/subscriptions/debtors/export/",
            "/api/v1/subscriptions/renewals/",
            f"/api/v1/subscriptions/?child_id={self.child.id}",
            f"/api/v1/payments/?child_id={self.child.id}",
            f"/api/v1/payments/requests/?child_id={self.child.id}",
        ):
            self.assertEqual(client.get(url).status_code, 403, url)

    def test_teacher_reads_money_when_allowed_but_cannot_change_it(self):
        self.set_access(teacher_sees_finances=True)
        permissions = self.permissions(self.teacher)
        self.assertTrue(permissions["can_view_client_money"])
        self.assertFalse(permissions["can_change_client_money"])
        self.assertFalse(permissions["can_accept_payments"])
        self.assertFalse(permissions["can_view_financials"])
        client = self.as_user(self.teacher)
        debtors = client.get("/api/v1/subscriptions/debtors/")
        self.assertEqual(debtors.status_code, 200)
        self.assertEqual(debtors.data["total_debt"], "20000")
        self.assertEqual(client.get("/api/v1/subscriptions/renewals/").status_code, 200)
        subs = client.get("/api/v1/subscriptions/", {"child_id": self.child.id})
        self.assertEqual(len(rows(subs)), 1)
        payments = client.get("/api/v1/payments/", {"child_id": self.child.id})
        self.assertEqual(len(rows(payments)), 1)
        sid = self.subscription.id
        for url in (
            f"/api/v1/subscriptions/{sid}/recompute/",
            f"/api/v1/subscriptions/{sid}/freeze/",
            f"/api/v1/subscriptions/renewals/{sid}/contacted/",
            "/api/v1/subscriptions/sell/",
            "/api/v1/payments/",
        ):
            self.assertEqual(client.post(url, {}, format="json").status_code, 403, url)

    def test_finances_without_phones_keep_phones_out_of_lists_and_excel(self):
        self.set_access(teacher_sees_finances=True)
        row = self.as_user(self.teacher).get("/api/v1/subscriptions/debtors/").data["results"][0]
        self.assertIsNone(row["phone"])
        self.assertIsNone(row["whatsapp"])
        self.assertNotIn("Телефон", self.export_header(self.teacher))
        self.set_access(teacher_sees_parent_phones=True)
        self.assertIn("Телефон", self.export_header(self.teacher))

    def test_switching_off_closes_access_on_next_request(self):
        self.set_access(teacher_sees_finances=True)
        client = self.as_user(self.teacher)
        self.assertEqual(client.get("/api/v1/subscriptions/debtors/").status_code, 200)
        self.set_access(teacher_sees_finances=False)
        self.assertEqual(
            self.as_user(self.teacher).get("/api/v1/subscriptions/debtors/").status_code, 403
        )

    # --- сводка организации администратору ---

    def test_admin_analytics_closed_by_default_and_opened_by_setting(self):
        url = "/api/v1/analytics/risk-list/"
        self.assertEqual(self.as_user(self.admin).get(url).status_code, 403)
        self.set_access(admin_sees_org_summary=True)
        permissions = self.permissions(self.admin)
        self.assertTrue(permissions["can_view_analytics"])
        self.assertTrue(permissions["can_view_org_summary"])
        self.assertEqual(self.as_user(self.admin).get(url).status_code, 200)
        # Настройка администратора не открывает аналитику преподавателю.
        self.assertEqual(self.as_user(self.teacher).get(url).status_code, 403)

    def test_admin_summary_limited_to_own_branches(self):
        self.set_access(admin_sees_org_summary=True)
        response = self.as_user(self.admin).get(
            "/api/v1/analytics/risk-list/", {"branch": str(self.other_branch.id)}
        )
        self.assertEqual(response.status_code, 403)
