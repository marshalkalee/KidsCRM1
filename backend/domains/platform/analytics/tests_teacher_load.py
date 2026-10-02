from datetime import date, datetime, time, timedelta

import pytz
from rest_framework.test import APITestCase

from domains.people.clients.models import Child
from domains.platform.core.utils import today_for_org
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.schedule.models import Lesson

URL = "/api/v1/analytics/teacher-workload/"


class TeacherWorkloadApiTests(APITestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Центр", slug="teacher-load")
        self.branch = Branch.objects.create(organization=self.organization, name="Абая")
        self.other_branch = Branch.objects.create(organization=self.organization, name="Саина")
        self.ballet = Direction.objects.create(organization=self.organization, name="Балет")
        self.chess = Direction.objects.create(organization=self.organization, name="Шахматы")
        self.owner = self.user("+77015550200", User.Role.OWNER, "Владелец")
        self.anna = self.user("+77015550201", User.Role.TEACHER, "Анна")
        self.boris = self.user("+77015550202", User.Role.TEACHER, "Борис")
        self.empty = self.user("+77015550203", User.Role.TEACHER, "Без занятий")
        self.anna.branches.add(self.branch)
        self.boris.branches.add(self.other_branch)
        self.today = today_for_org(self.organization)
        self.timezone = pytz.timezone(self.organization.timezone)
        self.anna_group = self.group("Балет 1", self.branch, self.ballet, 10, 3, self.anna)
        self.boris_group = self.group("Шахматы 1", self.other_branch, self.chess, 5, 4, self.boris)

        self.lesson(self.anna, self.anna_group, Lesson.Status.COMPLETED, 9)
        self.lesson(self.anna, self.anna_group, Lesson.Status.COMPLETED, 10)
        self.lesson(
            self.anna,
            self.anna_group,
            Lesson.Status.CANCELLED,
            11,
            Lesson.CancelReasonCategory.TEACHER_ILLNESS,
        )
        self.lesson(self.anna, self.anna_group, Lesson.Status.SCHEDULED, 12)
        self.lesson(self.anna, self.anna_group, Lesson.Status.RESCHEDULED, 13)
        self.lesson(self.boris, self.boris_group, Lesson.Status.COMPLETED, 14)
        self.lesson(self.boris, self.boris_group, Lesson.Status.COMPLETED, 15)
        self.client.force_authenticate(self.owner)

    def user(self, phone, role, name):
        return User.objects.create_user(
            organization=self.organization,
            phone=phone,
            password="x",
            full_name=name,
            role=role,
        )

    def group(self, name, branch, direction, capacity, members, teacher):
        group = Group.objects.create(
            organization=self.organization,
            branch=branch,
            direction=direction,
            name=name,
            capacity=capacity,
        )
        group.teachers.add(teacher)
        for index in range(members):
            child = Child.objects.create(
                organization=self.organization,
                full_name=f"{name} {index}",
                birth_date=date(2018, 1, 1),
                gender="female",
            )
            GroupMembership.objects.create(
                organization=self.organization,
                group=group,
                child=child,
                joined_at=self.today - timedelta(days=60),
            )
        return group

    def lesson(self, teacher, group, status, hour, reason=""):
        starts_at = self.timezone.localize(datetime.combine(self.today, time(hour)))
        return Lesson.objects.create(
            organization=self.organization,
            teacher=teacher,
            group=group,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(hours=1),
            status=status,
            cancel_reason_category=reason,
        )

    def test_load_matches_schedule_and_does_not_rate_quality(self):
        response = self.client.get(URL, {"period": "month"})
        self.assertEqual(response.status_code, 200)
        data = response.data
        rows = {row["name"]: row for row in data["teachers"]}
        self.assertEqual(set(rows), {"Анна", "Борис", "Без занятий"})
        self.assertEqual(
            {key: rows["Анна"][key] for key in ("planned", "completed", "scheduled", "cancelled")},
            {"planned": 4, "completed": 2, "scheduled": 1, "cancelled": 1},
        )
        self.assertEqual(rows["Анна"]["students"], 3)
        self.assertEqual(rows["Анна"]["fill_percent"], 30.0)
        self.assertEqual(rows["Анна"]["teacher_cancelled"], 1)
        self.assertNotIn("efficiency", rows["Анна"])
        self.assertEqual(rows["Без занятий"]["planned"], 0)
        self.assertEqual(data["summary"]["planned"], 6)

    def test_direction_teacher_and_branch_filters(self):
        ballet = self.client.get(URL, {"direction": str(self.ballet.id)}).data
        self.assertEqual([row["name"] for row in ballet["teachers"]], ["Анна"])
        teacher = self.client.get(URL, {"teacher": str(self.boris.id)}).data
        self.assertEqual([row["name"] for row in teacher["teachers"]], ["Борис"])
        branch = self.client.get(URL, {"branch": str(self.branch.id)}).data
        self.assertEqual({row["name"] for row in branch["teachers"]}, {"Анна"})
        self.assertEqual(branch["breakdowns"]["branch"][0]["label"], "Абая")

    def test_cancellations_trend_and_excel(self):
        data = self.client.get(URL, {"period": "year"}).data
        self.assertEqual(data["cancel_reasons"][0]["key"], "teacher_illness")
        self.assertTrue(data["cancel_reasons"][0]["teacher_fault"])
        anna = next(row for row in data["teachers"] if row["name"] == "Анна")
        self.assertEqual(sum(point["planned"] for point in anna["trend"]), 4)

        export = self.client.get(
            "/api/v1/analytics/export/", {"report": "teacher_workload", "period": "year"}
        )
        self.assertEqual(export.status_code, 200)
        self.assertTrue(export.content.startswith(b"PK"))
