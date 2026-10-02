from datetime import date, datetime, time, timedelta

import pytz
from rest_framework.test import APITestCase

from domains.people.clients.models import Child
from domains.platform.core.utils import today_for_org
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User
from domains.scheduling.attendance.models import Attendance
from domains.scheduling.groups.models import Group
from domains.scheduling.schedule.models import Lesson

URL = "/api/v1/analytics/attendance-trends/"


class AttendanceTrendsApiTests(APITestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Центр", slug="attendance-trends")
        self.branch = Branch.objects.create(organization=self.organization, name="Абая")
        self.other_branch = Branch.objects.create(organization=self.organization, name="Саина")
        self.direction = Direction.objects.create(organization=self.organization, name="Балет")
        self.teacher = User.objects.create_user(
            organization=self.organization,
            phone="+77015550301",
            password="x",
            full_name="Анна Петрова",
            role=User.Role.TEACHER,
        )
        self.owner = User.objects.create_user(
            organization=self.organization,
            phone="+77015550302",
            password="x",
            full_name="Владелец",
            role=User.Role.OWNER,
        )
        self.group = Group.objects.create(
            organization=self.organization,
            branch=self.branch,
            direction=self.direction,
            name="Младшая",
            capacity=12,
        )
        self.group.teachers.add(self.teacher)
        self.other_group = Group.objects.create(
            organization=self.organization,
            branch=self.other_branch,
            direction=self.direction,
            name="Старшая",
            capacity=12,
        )
        self.stable = self.child("Алия")
        self.chronic = self.child("Мира")
        self.today = today_for_org(self.organization)
        self.period_start = self.today - timedelta(days=27)
        self.tz = pytz.timezone(self.organization.timezone)
        self.client.force_authenticate(self.owner)

    def child(self, name):
        return Child.objects.create(
            organization=self.organization,
            full_name=name,
            birth_date=date(2018, 1, 1),
            gender=Child.Gender.FEMALE,
        )

    def lesson(self, day, group=None):
        starts_at = self.tz.localize(datetime.combine(day, time(18)))
        return Lesson.objects.create(
            organization=self.organization,
            group=group or self.group,
            teacher=self.teacher,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(hours=1),
            status=Lesson.Status.COMPLETED,
        )

    def mark(self, lesson, child, status, reason=""):
        return Attendance.objects.create(
            organization=self.organization,
            lesson=lesson,
            child=child,
            status=status,
            absence_reason=reason,
        )

    def params(self, **extra):
        return {
            "period": "custom",
            "from": self.period_start.isoformat(),
            "to": self.today.isoformat(),
            **extra,
        }

    def seed_personal_baseline(self):
        # Алия раньше не пропускала; Мира стабильно пропускала половину.
        for index, days_before in enumerate((55, 42, 28, 14)):
            lesson = self.lesson(self.period_start - timedelta(days=days_before))
            self.mark(lesson, self.stable, Attendance.Status.PRESENT)
            self.mark(
                lesson,
                self.chronic,
                Attendance.Status.ABSENT if index % 2 == 0 else Attendance.Status.PRESENT,
                Attendance.AbsenceReason.FAMILY if index % 2 == 0 else "",
            )

    def seed_current_period(self):
        first = self.lesson(self.period_start + timedelta(days=3))
        second = self.lesson(self.period_start + timedelta(days=11))
        self.mark(first, self.stable, Attendance.Status.PRESENT)
        self.mark(
            first,
            self.chronic,
            Attendance.Status.ABSENT,
            Attendance.AbsenceReason.ILLNESS,
        )
        self.mark(
            second,
            self.stable,
            Attendance.Status.ABSENT,
            Attendance.AbsenceReason.NO_REASON,
        )
        self.mark(second, self.chronic, Attendance.Status.PRESENT)

    def test_summary_weekly_breakdowns_and_reasons_match_marks(self):
        self.seed_personal_baseline()
        self.seed_current_period()

        response = self.client.get(URL, self.params())

        self.assertEqual(response.status_code, 200)
        data = response.data
        self.assertEqual(
            data["summary"],
            {
                "lessons_held": 2,
                "marked": 4,
                "attended": 2,
                "absences": 2,
                "attendance_rate": 50.0,
            },
        )
        self.assertEqual(sum(row["attended"] for row in data["weekly"]), 2)
        self.assertEqual(sum(row["absences"] for row in data["weekly"]), 2)
        self.assertEqual(
            {row["key"]: row["value"] for row in data["absence_reasons"]},
            {"illness": 1, "no_reason": 1},
        )
        for dimension in ("group", "direction", "branch", "teacher"):
            row = data["breakdowns"][dimension][0]
            self.assertEqual((row["lessons_held"], row["marked"], row["value"]), (2, 4, 50.0))
        self.assertEqual(len(data["breakdowns"]["weekday"]), 2)

    def test_personal_baseline_uses_change_not_a_common_absence_count(self):
        self.seed_personal_baseline()
        self.seed_current_period()

        children = {
            row["name"]: row for row in self.client.get(URL, self.params()).data["children"]
        }

        stable = children["Алия"]
        chronic = children["Мира"]
        self.assertEqual(stable["absence_rate"], 50.0)
        self.assertEqual(stable["baseline"]["absence_rate"], 0.0)
        self.assertEqual((stable["absence_change_pp"], stable["trend"]), (50.0, "rising"))
        self.assertEqual(chronic["absence_rate"], 50.0)
        self.assertEqual(chronic["baseline"]["absence_rate"], 50.0)
        self.assertEqual((chronic["absence_change_pp"], chronic["trend"]), (0.0, "stable"))

    def test_branch_scope_and_excel_export(self):
        self.seed_current_period()
        other = self.lesson(self.period_start + timedelta(days=4), self.other_group)
        self.mark(other, self.stable, Attendance.Status.ABSENT)

        scoped = self.client.get(URL, self.params(branch=str(self.branch.id)))
        self.assertEqual(scoped.status_code, 200)
        self.assertEqual(scoped.data["summary"]["lessons_held"], 2)
        self.assertEqual(scoped.data["summary"]["marked"], 4)

        export = self.client.get(
            "/api/v1/analytics/export/",
            {**self.params(branch=str(self.branch.id)), "report": "attendance"},
        )
        self.assertEqual(export.status_code, 200)
        self.assertEqual(
            export["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertTrue(export.content.startswith(b"PK"))
