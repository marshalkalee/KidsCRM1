"""
Средние проблемы, найденные при QA-проходе:
1. управляющий без выбранных филиалов (= все) не открывал филиал и его залы;
2. проверки на сервере: PATCH одного конца занятия/шаблона, слот 0 минут,
   пароль сотрудника, «безлимит» без числа занятий (500);
3. границы дат: рождение, начало абонемента, дата оплаты;
4. телефоны сотрудников в общем списке — только с правом их видеть.
"""

import datetime

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from domains.money.subscriptions.models import Subscription
from domains.money.subscriptions.subscription_types import create_type
from domains.people.clients.models import Child
from domains.platform.core.utils import years_ago
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group
from domains.scheduling.schedule.models import Lesson
from domains.scheduling.schedule_templates.models import ScheduleTemplate, ScheduleTemplateSlot


def client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    refresh["organization_id"] = str(user.organization_id)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


class QaFixesBase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="QA", slug="qa")
        self.branch_a = Branch.objects.create(organization=self.org, name="Абая")
        self.branch_b = Branch.objects.create(organization=self.org, name="Орбита")
        self.direction = Direction.objects.create(organization=self.org, name="Балет")

        def user(phone, role, **extra):
            return User.objects.create_user(
                phone=phone,
                password="Qwerty12345!",
                full_name=f"Сотрудник {role}",
                organization=self.org,
                role=role,
                **extra,
            )

        self.owner = user("+77030000001", User.Role.OWNER)
        self.manager = user("+77030000002", User.Role.MANAGER)
        self.teacher = user("+77030000003", User.Role.TEACHER)
        self.admin = user("+77030000004", User.Role.ADMIN)
        self.today = timezone.localdate()


class BranchAccessTests(QaFixesBase):
    def test_manager_without_branches_opens_any_branch(self):
        response = client_for(self.manager).get(f"/api/v1/branches/{self.branch_b.id}/")
        self.assertEqual(response.status_code, 200)

    def test_manager_with_branches_does_not_open_others(self):
        self.manager.branches.set([self.branch_a])
        client = client_for(self.manager)
        self.assertEqual(client.get(f"/api/v1/branches/{self.branch_a.id}/").status_code, 200)
        self.assertIn(client.get(f"/api/v1/branches/{self.branch_b.id}/").status_code, (403, 404))


class ServerValidationTests(QaFixesBase):
    def setUp(self):
        super().setUp()
        self.group = Group.objects.create(
            organization=self.org,
            branch=self.branch_a,
            direction=self.direction,
            name="Балет 6–8",
            capacity=10,
        )
        starts = timezone.now() + datetime.timedelta(days=3)
        self.lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            starts_at=starts,
            ends_at=starts + datetime.timedelta(hours=1),
        )
        self.template = ScheduleTemplate.objects.create(
            organization=self.org, group=self.group, valid_from=self.today
        )
        self.slot = ScheduleTemplateSlot.objects.create(
            organization=self.org,
            template=self.template,
            weekday=0,
            start_time=datetime.time(15, 0),
        )
        self.client = client_for(self.owner)

    def test_lesson_patch_of_one_end_is_checked_against_the_other(self):
        before_start = (self.lesson.starts_at - datetime.timedelta(hours=1)).isoformat()
        after_end = (self.lesson.ends_at + datetime.timedelta(hours=5)).isoformat()
        for payload in ({"ends_at": before_start}, {"starts_at": after_end}):
            response = self.client.patch(
                f"/api/v1/schedule/{self.lesson.id}/", payload, format="json"
            )
            self.assertEqual(response.status_code, 400, payload)
            self.assertIn("ends_at", response.data)
        self.lesson.refresh_from_db()
        self.assertLess(self.lesson.starts_at, self.lesson.ends_at)

    def test_template_patch_of_end_is_checked_against_start(self):
        response = self.client.patch(
            f"/api/v1/schedule-templates/{self.template.id}/",
            {"valid_until": str(self.today - datetime.timedelta(days=30))},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("valid_until", response.data)

    def test_slot_duration_has_bounds(self):
        url = f"/api/v1/schedule-templates/{self.template.id}/slots/{self.slot.id}/"
        for minutes in (0, 10, 361):
            response = self.client.patch(url, {"duration_minutes": minutes}, format="json")
            self.assertEqual(response.status_code, 400, minutes)
        self.assertEqual(
            self.client.patch(url, {"duration_minutes": 45}, format="json").status_code, 200
        )

    def _create_staff(self, **extra):
        payload = {"full_name": "Новый Сотрудник", "phone": "+77030000099", "role": "teacher"}
        return self.client.post("/api/v1/users/", {**payload, **extra}, format="json")

    def test_staff_password_is_required_and_checked(self):
        for extra in ({}, {"password": "1"}, {"password": "12345678"}):
            response = self._create_staff(**extra)
            self.assertEqual(response.status_code, 400, extra)
            self.assertIn("password", response.data)
        self.assertEqual(self._create_staff(password="Qwerty12345!").status_code, 201)

    def test_staff_edit_without_password_keeps_it(self):
        response = self.client.patch(
            f"/api/v1/users/{self.teacher.id}/", {"full_name": "Новое Имя"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.teacher.refresh_from_db()
        self.assertTrue(self.teacher.check_password("Qwerty12345!"))

    def test_unlimited_switch_alone_is_not_500(self):
        st = create_type(
            self.org, name="8 занятий", price=25000, quota_sessions=8, duration_days=30
        )
        url = f"/api/v1/subscriptions/subscription-types/{st.id}/"

        response = self.client.patch(url, {"is_unlimited": True}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(response.data["quota_sessions"])

        # У безлимитного нет числа занятий; обратно — только с числом.
        self.assertEqual(
            self.client.patch(url, {"quota_sessions": 5}, format="json").status_code, 400
        )
        self.assertEqual(
            self.client.patch(url, {"is_unlimited": False}, format="json").status_code, 400
        )
        response = self.client.patch(
            url, {"is_unlimited": False, "quota_sessions": 12}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["quota_sessions"], 12)


class DateBoundsTests(QaFixesBase):
    def setUp(self):
        super().setUp()
        self.client = client_for(self.owner)
        self.child = Child.objects.create(
            organization=self.org,
            full_name="Иванов Алихан",
            birth_date=datetime.date(2018, 1, 1),
            gender=Child.Gender.MALE,
        )
        self.st = create_type(
            self.org,
            name="8 занятий",
            price=25000,
            quota_sessions=8,
            duration_days=30,
            directions=[self.direction],
        )

    def _child(self, birth_date):
        return self.client.post(
            "/api/v1/clients/children/",
            {"full_name": "Тест Возраст", "birth_date": str(birth_date), "gender": "male"},
            format="json",
        )

    def test_birth_date_older_than_25_years_is_rejected(self):
        self.assertEqual(self._child(datetime.date(1900, 1, 1)).status_code, 400)
        self.assertEqual(self._child(years_ago(self.today, 26)).status_code, 400)
        oldest = years_ago(self.today, 26) + datetime.timedelta(days=1)
        self.assertEqual(self._child(oldest).status_code, 201)

    def _sell(self, starts_on):
        return self.client.post(
            "/api/v1/subscriptions/sell/",
            {
                "child_id": str(self.child.id),
                "branch_id": str(self.branch_a.id),
                "direction_id": str(self.direction.id),
                "subscription_type_id": str(self.st.id),
                "starts_on": str(starts_on),
            },
            format="json",
        )

    def test_subscription_start_is_within_a_year(self):
        for starts_on in (datetime.date(1900, 1, 1), datetime.date(2100, 1, 1)):
            response = self._sell(starts_on)
            self.assertEqual(response.status_code, 400, starts_on)
            self.assertIn("starts_on", response.data)
        self.assertEqual(self._sell(self.today - datetime.timedelta(days=30)).status_code, 201)

    def test_payment_date_is_not_older_than_a_year(self):
        sub = Subscription.objects.create(
            organization=self.org,
            child=self.child,
            subscription_type_version=self.st.versions.latest(),
            direction=self.direction,
            starts_on=self.today,
            ends_on=self.today + datetime.timedelta(days=30),
            list_price=25000,
            price=25000,
        )

        def pay(paid_on):
            return self.client.post(
                "/api/v1/payments/",
                {
                    "subscription": str(sub.id),
                    "amount": 1000,
                    "method": "cash",
                    "paid_on": str(paid_on),
                },
                format="json",
            )

        response = pay(years_ago(self.today, 2))
        self.assertEqual(response.status_code, 400)
        self.assertIn("paid_on", response.data)
        self.assertEqual(pay(self.today - datetime.timedelta(days=60)).status_code, 201)


class StaffPhoneVisibilityTests(QaFixesBase):
    def phones(self, user):
        response = client_for(user).get("/api/v1/users/")
        return {row["full_name"]: row.get("phone") for row in response.data["results"]}

    def test_teacher_sees_only_own_phone(self):
        phones = self.phones(self.teacher)
        self.assertEqual(phones[self.teacher.full_name], self.teacher.phone)
        self.assertIsNone(phones[self.owner.full_name])
        self.assertIsNone(phones[self.admin.full_name])

    def test_staff_with_phone_access_sees_phones(self):
        for user in (self.admin, self.manager, self.owner):
            self.assertEqual(self.phones(user)[self.teacher.full_name], self.teacher.phone)
