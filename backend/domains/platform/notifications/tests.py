import datetime

from django.test import TestCase, tag
from django.utils import timezone
from rest_framework.test import APIClient

from domains.money.subscriptions.models import Subscription
from domains.money.subscriptions.sales import sell_subscription
from domains.money.subscriptions.subscription_types import create_type
from domains.people.clients.models import Child
from domains.platform.leads.services import create_lead
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User
from domains.scheduling.attendance.models import Attendance
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.schedule.models import Lesson

URL = "/api/v1/notifications/"
TZ = timezone.zoneinfo.ZoneInfo("Asia/Almaty")


def client_for(user, branch=None):
    client = APIClient()
    client.force_authenticate(user=user)
    if branch is not None:
        client.defaults["HTTP_X_BRANCH_ID"] = str(branch.id)
    return client


def by_kind(response):
    return {item["kind"]: item for item in response.data["items"]}


class NotificationFixtures(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="tb")
        self.center = Branch.objects.create(organization=self.org, name="Центр")
        self.orbit = Branch.objects.create(organization=self.org, name="Орбита")
        self.direction = Direction.objects.create(organization=self.org, name="Балет")
        self.owner = self.user("77010000001", User.Role.OWNER)
        self.admin = self.user("77010000002", User.Role.ADMIN, branches=[self.center])
        self.teacher = self.user("77010000003", User.Role.TEACHER)
        self.accountant = self.user("77010000004", User.Role.ACCOUNTANT)
        self.group_center = self.group(self.center, "Центр 5–7")
        self.group_orbit = self.group(self.orbit, "Орбита 5–7")
        self.version = create_type(
            self.org,
            name="8 занятий",
            price=25000,
            quota_sessions=8,
            duration_days=30,
            directions=[self.direction],
        ).versions.latest()

    def user(self, phone, role, branches=()):
        user = User.objects.create_user(
            phone=phone, password="pass", full_name=role, organization=self.org, role=role
        )
        user.branches.set(branches)
        return user

    def group(self, branch, name):
        return Group.objects.create(
            organization=self.org, branch=branch, direction=self.direction, name=name, capacity=12
        )

    def child(self, name, group=None):
        child = Child.objects.create(
            organization=self.org,
            full_name=name,
            birth_date=datetime.date(2019, 1, 1),
            gender=Child.Gender.FEMALE,
        )
        if group is not None:
            GroupMembership.objects.create(
                organization=self.org, group=group, child=child, joined_at=datetime.date.today()
            )
        return child

    def sell(self, child, branch, paid, days_ago=0):
        starts = datetime.date.today() - datetime.timedelta(days=days_ago)
        sub, _ = sell_subscription(
            actor=self.owner,
            child=child,
            subscription_type_version=self.version,
            direction=self.direction,
            branch=branch,
            starts_on=starts,
            paid_amount=paid,
            payment_method="cash",
        )
        return sub

    def yesterday_lesson(self, group, teacher=None):
        day = timezone.now().astimezone(TZ).date() - datetime.timedelta(days=1)
        start = datetime.datetime.combine(day, datetime.time(15, 0), tzinfo=TZ)
        return Lesson.objects.create(
            organization=self.org,
            group=group,
            teacher=teacher,
            starts_at=start,
            ends_at=start + datetime.timedelta(hours=1),
        )


class NotificationKindsTests(NotificationFixtures):
    def test_new_leads(self):
        create_lead(
            organization=self.org,
            actor=self.owner,
            parent_name="А",
            phone="+77070000001",
            branch=self.center,
        )
        create_lead(
            organization=self.org,
            actor=self.owner,
            parent_name="Б",
            phone="+77070000002",
            branch=self.orbit,
        )
        item = by_kind(client_for(self.owner).get(URL))["new_leads"]
        self.assertEqual((item["count"], item["unread"], item["link"]), (2, True, "/leads"))
        # Администратор центра не видит заявку чужого филиала.
        self.assertEqual(by_kind(client_for(self.admin).get(URL))["new_leads"]["count"], 1)

    def test_unmarked_lessons(self):
        a, b = self.child("Алия", self.group_center), self.child("Бота", self.group_center)
        lesson = self.yesterday_lesson(self.group_center, teacher=self.teacher)
        Attendance.objects.create(organization=self.org, lesson=lesson, child=a, status="absent")
        item = by_kind(client_for(self.owner).get(URL))["unmarked_lessons"]
        self.assertEqual(item["count"], 1)
        # Одно занятие — ведём прямо в него.
        self.assertEqual(item["link"], f"/attendance?lesson={lesson.id}")
        self.assertEqual(by_kind(client_for(self.teacher).get(URL))["unmarked_lessons"]["count"], 1)
        Attendance.objects.create(organization=self.org, lesson=lesson, child=b, status="absent")
        self.assertEqual(by_kind(client_for(self.owner).get(URL))["unmarked_lessons"]["count"], 0)

    def test_teacher_sees_only_own_lessons(self):
        self.child("Алия", self.group_center)
        self.yesterday_lesson(self.group_center, teacher=self.owner)
        self.assertEqual(by_kind(client_for(self.teacher).get(URL))["unmarked_lessons"]["count"], 0)

    def test_cancelled_lesson_not_counted(self):
        self.child("Алия", self.group_center)
        lesson = self.yesterday_lesson(self.group_center)
        Lesson.objects.filter(pk=lesson.pk).update(status=Lesson.Status.CANCELLED)
        self.assertEqual(by_kind(client_for(self.owner).get(URL))["unmarked_lessons"]["count"], 0)

    def test_no_subscription_matches_children_filter(self):
        with_sub = self.child("С абонементом", self.group_center)
        self.sell(with_sub, self.center, paid=25000)
        self.child("Без абонемента", self.group_center)
        self.child("Без группы")  # не занимается — не считаем
        left = self.child("Ушла", self.group_center)
        Child.objects.filter(pk=left.pk).update(status=Child.Status.LEFT)
        item = by_kind(client_for(self.owner).get(URL))["no_subscription"]
        self.assertEqual((item["count"], item["link"]), (1, "/children?no_subscription=1"))
        listed = (
            client_for(self.owner)
            .get("/api/v1/clients/children/table/", {"no_subscription": "1"})
            .data
        )
        self.assertEqual([row["full_name"] for row in listed["results"]], ["Без абонемента"])

    def test_overdue_debts_match_children_filter(self):
        old = self.child("Старый долг", self.group_center)
        self.sell(old, self.center, paid=5000, days_ago=10)
        fresh = self.child("Свежий долг", self.group_center)
        self.sell(fresh, self.center, paid=5000, days_ago=1)
        item = by_kind(client_for(self.owner).get(URL))["overdue_debts"]
        self.assertEqual((item["count"], item["total"], item["days"]), (1, "20000", 5))
        listed = (
            client_for(self.owner)
            .get("/api/v1/clients/children/table/", {"has_debt": "1", "debt_overdue": "1"})
            .data
        )
        self.assertEqual([row["full_name"] for row in listed["results"]], ["Старый долг"])

    def test_threshold_from_settings(self):
        child = self.child("Долг", self.group_center)
        self.sell(child, self.center, paid=5000, days_ago=10)
        self.org.settings = {**self.org.settings, "debt_overdue_days_threshold": 30}
        self.org.save()
        self.assertEqual(by_kind(client_for(self.owner).get(URL))["overdue_debts"]["count"], 0)

    def test_overdue_tasks_counts_real_open_overdue(self):
        from datetime import timedelta

        from django.utils import timezone

        from domains.platform.tasks.models import Task
        from domains.platform.tasks.services import create_task

        create_task(
            type=Task.Type.OTHER,
            assignee=self.owner,
            due_date=timezone.now() - timedelta(days=1),
            subject="Просрочена",
            organization=self.owner.organization,
        )
        item = by_kind(client_for(self.owner).get(URL))["overdue_tasks"]
        self.assertEqual((item["available"], item["count"]), (True, 1))


class NotificationRolesAndBranchesTests(NotificationFixtures):
    def test_kinds_by_role(self):
        self.assertEqual(
            set(by_kind(client_for(self.owner).get(URL))),
            {
                "new_leads",
                "parent_requests",
                "unmarked_lessons",
                "overdue_debts",
                "no_subscription",
                "overdue_tasks",
                "ai_digest",
            },
        )
        self.assertEqual(set(by_kind(client_for(self.teacher).get(URL))), {"unmarked_lessons"})
        self.assertEqual(
            set(by_kind(client_for(self.accountant).get(URL))), {"overdue_debts", "no_subscription"}
        )

    def test_admin_sees_only_own_branch(self):
        center_kid = self.child("Центр", self.group_center)
        orbit_kid = self.child("Орбита", self.group_orbit)
        self.sell(center_kid, self.center, paid=5000, days_ago=10)
        self.sell(orbit_kid, self.orbit, paid=5000, days_ago=10)
        self.child("Центр без абонемента", self.group_center)
        self.child("Орбита без абонемента", self.group_orbit)
        admin = by_kind(client_for(self.admin).get(URL))
        self.assertEqual(
            (admin["overdue_debts"]["count"], admin["no_subscription"]["count"]), (1, 1)
        )
        owner = by_kind(client_for(self.owner).get(URL))
        self.assertEqual(
            (owner["overdue_debts"]["count"], owner["no_subscription"]["count"]), (2, 2)
        )
        # Шапка владельца сужает до филиала; админу чужой филиал шапкой не открыть.
        self.assertEqual(
            by_kind(client_for(self.owner, self.orbit).get(URL))["overdue_debts"]["count"], 1
        )
        self.assertEqual(
            by_kind(client_for(self.admin, self.orbit).get(URL))["overdue_debts"]["count"], 1
        )
        self.assertEqual(
            by_kind(client_for(self.admin, self.orbit).get(URL))["overdue_debts"]["total"], "20000"
        )


class NotificationSeenTests(NotificationFixtures):
    def test_mark_seen_and_new_items_become_unread_again(self):
        create_lead(organization=self.org, actor=self.owner, parent_name="А", phone="+77070000001")
        client = client_for(self.owner)
        self.assertEqual(client.get(URL).data["unread"], 1)
        response = client.post(f"{URL}seen/", {"kind": "new_leads"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(by_kind(response)["new_leads"]["unread"])
        self.assertEqual(response.data["unread"], 0)
        create_lead(organization=self.org, actor=self.owner, parent_name="Б", phone="+77070000002")
        self.assertTrue(by_kind(client.get(URL))["new_leads"]["unread"])

    def test_count_based_kind(self):
        self.child("Без абонемента 1", self.group_center)
        client = client_for(self.owner)
        client.post(f"{URL}seen/", {"kind": "no_subscription"}, format="json")
        self.assertFalse(by_kind(client.get(URL))["no_subscription"]["unread"])
        self.child("Без абонемента 2", self.group_center)
        self.assertTrue(by_kind(client.get(URL))["no_subscription"]["unread"])

    def test_mark_all_and_per_user(self):
        create_lead(organization=self.org, actor=self.owner, parent_name="А", phone="+77070000001")
        self.child("Без абонемента", self.group_center)
        response = client_for(self.owner).post(f"{URL}seen/", {"kind": "all"}, format="json")
        self.assertEqual(response.data["unread"], 0)
        # «Прочитано» — у каждого сотрудника своё.
        self.assertGreater(client_for(self.admin).get(URL).data["unread"], 0)

    def test_unknown_kind(self):
        self.assertEqual(
            client_for(self.teacher)
            .post(f"{URL}seen/", {"kind": "new_leads"}, format="json")
            .status_code,
            400,
        )

    def test_requires_login(self):
        self.assertEqual(APIClient().get(URL).status_code, 401)


@tag("tenant_isolation")
class NotificationTenantIsolationTests(NotificationFixtures):
    def test_other_org_data_not_counted(self):
        create_lead(organization=self.org, actor=self.owner, parent_name="А", phone="+77070000001")
        self.child("Без абонемента", self.group_center)
        other = Organization.objects.create(name="Чужой", slug="other")
        other_owner = User.objects.create_user(
            phone="77090000001",
            password="pass",
            full_name="Чужой",
            organization=other,
            role=User.Role.OWNER,
        )
        items = by_kind(client_for(other_owner).get(URL))
        self.assertEqual((items["new_leads"]["count"], items["no_subscription"]["count"]), (0, 0))
        self.assertEqual(Subscription.objects.for_tenant(other).count(), 0)
