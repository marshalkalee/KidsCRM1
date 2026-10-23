"""
Особые права сотрудника поверх роли: владелец даёт или забирает конкретному
человеку одно из role_permissions.OVERRIDABLE, и сервер проверяет то же,
что показывает фронтенд.
"""

from datetime import date, timedelta
from uuid import uuid4

from rest_framework.test import APITestCase

from domains.money.subscriptions.models import Subscription
from domains.money.subscriptions.sales import sell_subscription
from domains.money.subscriptions.subscription_types import create_type
from domains.people.clients.models import Child
from domains.platform.core.audit import AuditLog
from domains.platform.core.role_permissions import get_user_permissions
from domains.platform.tenants.models import Direction, Organization
from domains.platform.users.models import User


class PermissionOverrideTests(APITestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="overrides")
        self.ballet = Direction.objects.create(organization=self.org, name="Балет")
        self.owner = self.user("+77010000001", User.Role.OWNER)
        self.manager = self.user("+77010000002", User.Role.MANAGER)
        self.admin = self.user("+77010000003", User.Role.ADMIN)
        self.teacher = self.user("+77010000004", User.Role.TEACHER)
        self.child = Child.objects.create(
            organization=self.org, full_name="Иванова Алия", birth_date=date(2018, 1, 1)
        )
        self.type = create_type(
            self.org,
            name="8 занятий",
            price=30000,
            quota_sessions=8,
            duration_days=30,
            directions=[self.ballet],
        )

    def user(self, phone, role):
        return User.objects.create_user(
            phone=phone, password="x", full_name=role, organization=self.org, role=role
        )

    def access(self, target, actor=None, overrides=None):
        self.client.force_authenticate(actor or self.owner)
        url = f"/api/v1/users/{target.pk}/access/"
        if overrides is None:
            return self.client.get(url)
        return self.client.put(url, {"overrides": overrides}, format="json")

    def items(self, response):
        return {item["key"]: item for item in response.data["items"]}

    def subscription(self):
        return Subscription.objects.create(
            organization=self.org,
            child=self.child,
            subscription_type_version=self.type.versions.latest(),
            direction=self.ballet,
            starts_on=date.today(),
            ends_on=date.today() + timedelta(days=30),
            list_price=30000,
            price=30000,
        )

    def pay(self, user):
        self.client.force_authenticate(user)
        return self.client.post(
            "/api/v1/payments/",
            {
                "subscription": str(self.subscription().pk),
                "amount": "10000",
                "method": "kaspi_transfer",
                "idempotency_key": str(uuid4()),
            },
        )

    def test_owner_gives_one_teacher_parent_phones(self):
        other_teacher = self.user("+77010000005", User.Role.TEACHER)
        response = self.access(self.teacher, overrides={"can_view_phone": True})
        self.assertEqual(response.status_code, 200, response.data)
        phone = self.items(response)["can_view_phone"]
        self.assertEqual(
            (phone["role_default"], phone["override"], phone["effective"]), (False, True, True)
        )
        self.teacher.refresh_from_db()
        self.assertTrue(get_user_permissions(self.teacher)["can_view_phone"])
        # Остальным преподавателям — как у роли.
        self.assertFalse(get_user_permissions(other_teacher)["can_view_phone"])
        log = AuditLog.objects.get(object_id=self.teacher.pk, action=AuditLog.Action.GRANT)
        self.assertEqual(log.after, {"permission_overrides": {"can_view_phone": True}})

    def test_taking_payments_away_from_one_admin_is_enforced_by_api_and_sales(self):
        self.access(self.admin, overrides={"can_accept_payments": False})
        self.admin.refresh_from_db()
        self.assertEqual(self.pay(self.admin).status_code, 403)
        with self.assertRaisesMessage(ValueError, "нет права принимать оплаты"):
            sell_subscription(
                actor=self.admin,
                child=self.child,
                subscription_type_version=self.type.versions.latest(),
                direction=self.ballet,
                branch=None,
                starts_on=date.today(),
                paid_amount=10000,
                payment_method="cash",
            )
        # Продажа целиком откатилась — без «абонемента без оплаты».
        self.assertEqual(Subscription.objects.filter(child=self.child).count(), 1)
        # Другой администратор принимает как раньше.
        colleague = self.user("+77010000006", User.Role.ADMIN)
        self.assertEqual(self.pay(colleague).status_code, 201)

    def test_given_payments_open_the_api(self):
        accountant = self.user("+77010000007", User.Role.ACCOUNTANT)
        self.assertEqual(self.pay(accountant).status_code, 403)
        self.access(accountant, overrides={"can_accept_payments": True})
        accountant.refresh_from_db()
        self.assertEqual(self.pay(accountant).status_code, 201)

    def test_digest_and_analytics_for_one_admin(self):
        self.access(self.admin, overrides={"can_view_ai_digest": True, "can_view_analytics": True})
        self.admin.refresh_from_db()
        permissions = get_user_permissions(self.admin)
        self.assertTrue(permissions["can_view_ai_digest"])
        self.assertTrue(permissions["can_view_analytics"])
        self.client.force_authenticate(self.admin)
        # Дайджест пускает по праву (дальше — опция ИИ центра, не роль).
        self.assertNotEqual(self.client.get("/api/v1/ai/digests/").status_code, 401)

    def test_only_differences_from_role_are_stored_and_null_resets(self):
        self.access(self.admin, overrides={"can_manage_leads": True, "can_view_phone": False})
        self.admin.refresh_from_db()
        # Заявки администратору и так даёт роль — хранить нечего.
        self.assertEqual(self.admin.permission_overrides, {"can_view_phone": False})
        self.access(self.admin, overrides={"can_view_phone": None})
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.permission_overrides, {})

    def test_only_owner_changes_and_owner_has_everything(self):
        viewed = self.access(self.teacher, actor=self.manager)
        self.assertEqual(viewed.status_code, 200)
        self.assertFalse(viewed.data["editable"])
        self.assertEqual(
            self.access(
                self.teacher, actor=self.manager, overrides={"can_view_phone": True}
            ).status_code,
            403,
        )
        self.assertEqual(
            self.access(self.owner, overrides={"can_view_phone": False}).status_code, 403
        )
        self.assertEqual(self.access(self.teacher, actor=self.admin).status_code, 403)

    def test_dangerous_or_unknown_rights_cannot_be_given(self):
        response = self.access(self.teacher, overrides={"can_manage_staff": True})
        self.assertEqual(response.status_code, 400)
        response = self.access(self.teacher, overrides={"can_view_phone": "yes"})
        self.assertEqual(response.status_code, 400)
        # Даже если ключ попал в базу в обход API — он не действует.
        self.teacher.permission_overrides = {"can_manage_staff": True}
        self.teacher.save()
        self.assertFalse(get_user_permissions(self.teacher)["can_manage_staff"])

    def test_other_center_staff_is_not_reachable(self):
        other = Organization.objects.create(name="Другой", slug="overrides-other")
        stranger = User.objects.create_user(
            phone="+77019999999",
            password="x",
            full_name="Чужой",
            organization=other,
            role="teacher",
        )
        self.assertEqual(self.access(stranger, overrides={"can_view_phone": True}).status_code, 404)
        stranger.refresh_from_db()
        self.assertEqual(stranger.permission_overrides, {})
