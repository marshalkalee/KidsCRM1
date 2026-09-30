"""Сравнение филиалов (TRU-128)."""

import io
from datetime import datetime, time, timedelta

import openpyxl

from domains.platform.tenants.models import Branch, Organization
from domains.platform.users.models import User
from domains.scheduling.attendance.models import Attendance
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.schedule.models import Lesson

from .tests import AnalyticsFixtures

URL = "/api/v1/analytics/branches/"


class BranchCompareTests(AnalyticsFixtures):
    def setUp(self):
        super().setUp()
        # Абая: 2 ребёнка ходят, выручка 60 000; Саина: 1 ребёнок, 15 000.
        self.visit(self.abaya, 2)
        self.visit(self.saina, 1)
        self.pay(self.subscription(self.abaya), 30000)
        self.pay(self.subscription(self.abaya), 30000)
        self.pay(self.subscription(self.saina), 15000)
        self.client.force_authenticate(self.owner)

    def visit(self, branch, kids):
        group = Group.objects.create(
            organization=self.org,
            branch=branch,
            direction=self.ballet,
            name=f"Г {branch.name}",
            capacity=4,
        )
        start = self.tz.localize(datetime.combine(self.today, time(10)))
        lesson = Lesson.objects.create(
            organization=self.org, group=group, starts_at=start, ends_at=start + timedelta(hours=1)
        )
        for i in range(kids):
            child = self.child(f"{branch.name} {i}")
            GroupMembership.objects.create(
                organization=self.org, group=group, child=child, joined_at=self.today
            )
            Attendance.objects.create(
                organization=self.org, lesson=lesson, child=child, status="present"
            )

    def rows(self, **params):
        data = self.client.get(URL, params).data
        return data, {row["branch"]["name"]: row["values"] for row in data["rows"]}

    def test_normalized_next_to_absolute(self):
        data, rows = self.rows()
        self.assertTrue(data["comparable"])
        abaya, saina = rows["Абая"], rows["Саина"]
        self.assertEqual(
            (abaya["revenue"]["value"], abaya["active_children"]["value"]), ("60000", "2")
        )
        self.assertEqual(abaya["revenue_per_child"]["value"], "30000")
        self.assertEqual(saina["revenue_per_child"]["value"], "15000")
        self.assertEqual(abaya["average_check"]["value"], "30000")
        self.assertEqual(abaya["group_fill"]["value"], "50")
        self.assertEqual(data["total"]["revenue"]["value"], "75000")
        relative = {c["key"] for c in data["columns"] if c["relative"]}
        self.assertIn("revenue_per_child", relative)
        self.assertNotIn("revenue", relative)

    def test_same_numbers_as_single_branch_report(self):
        _, rows = self.rows()
        self.client.force_authenticate(self.owner)
        single = self.client.get(
            "/api/v1/analytics/metrics/",
            {
                "metrics": "revenue,average_check,attendance_rate,group_fill,active_children",
                "branch": str(self.abaya.pk),
            },
        ).data["metrics"]
        for name in (
            "revenue",
            "average_check",
            "attendance_rate",
            "group_fill",
            "active_children",
        ):
            self.assertEqual(rows["Абая"][name]["value"], str(single[name]["value"]), name)

    def test_manager_sees_only_own_branches(self):
        manager = self.user("+77010000002", User.Role.MANAGER, [self.abaya])
        self.client.force_authenticate(manager)
        data, rows = self.rows()
        self.assertEqual(list(rows), ["Абая"])
        self.assertFalse(data["comparable"])

    def test_single_branch_org_is_predictable(self):
        org = Organization.objects.create(name="Один филиал", slug="one-branch")
        Branch.objects.create(organization=org, name="Центр")
        owner = User.objects.create_user(
            phone="+77019990000",
            password="x",
            full_name="В",
            organization=org,
            role=User.Role.OWNER,
        )
        self.client.force_authenticate(owner)
        data = self.client.get(URL).data
        self.assertEqual((len(data["rows"]), data["comparable"]), (1, False))

    def test_plan_without_network_is_closed(self):
        Organization.objects.filter(pk=self.org.pk).update(plan="start")
        self.owner.organization.refresh_from_db()
        self.assertEqual(self.client.get(URL).status_code, 403)
        catalog = self.client.get("/api/v1/analytics/catalog/").data
        self.assertFalse(catalog["features"]["branch_compare"])
        Organization.objects.filter(pk=self.org.pk).update(plan="network")
        self.owner.organization.refresh_from_db()
        self.assertEqual(self.client.get(URL).status_code, 200)

    def test_trend_and_export(self):
        trend = self.client.get(f"{URL}trend/", {"metric": "revenue"}).data
        self.assertEqual({b["branch"]["name"] for b in trend["branches"]}, {"Абая", "Саина"})
        self.assertEqual(self.client.get(f"{URL}trend/", {"metric": "nope"}).status_code, 400)
        response = self.client.get("/api/v1/analytics/export/", {"report": "branches"})
        book = openpyxl.load_workbook(io.BytesIO(response.content))
        names = [row[0].value for row in book["Филиалы"].iter_rows()]
        self.assertIn("Абая", names)
        self.assertIn("Всего по выборке", names)
