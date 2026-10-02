"""Parent portal attendance history (TRU-142)."""

import datetime

from django.utils import timezone

from domains.people.clients.models import Child
from domains.platform.tenants.models import Direction
from domains.scheduling.attendance.models import Attendance
from domains.scheduling.groups.models import Group
from domains.scheduling.schedule.enrollment_service import MAKEUP_EXPIRY_DAYS
from domains.scheduling.schedule.models import Lesson

from .tests_auth import PortalAuthBase


class ParentAttendanceTests(PortalAuthBase):
    def setUp(self):
        super().setUp()
        self.branch = self.org.branch_set.first()
        self.direction = Direction.objects.create(organization=self.org, name="Балет")
        self.group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Балет 8–11",
            capacity=12,
        )
        self.tz = timezone.zoneinfo.ZoneInfo(self.org.timezone or "Asia/Almaty")
        self.today = timezone.now().astimezone(self.tz).date()

    def lesson(self, day, hour=18):
        starts_at = datetime.datetime.combine(day, datetime.time(hour), tzinfo=self.tz)
        return Lesson.objects.create(
            organization=self.org,
            group=self.group,
            starts_at=starts_at,
            ends_at=starts_at + datetime.timedelta(hours=1),
        )

    def mark(self, day, status, **extra):
        return Attendance.objects.create(
            organization=self.org,
            lesson=self.lesson(day),
            child=self.child,
            status=status,
            **extra,
        )

    def get(self, suffix=""):
        token = self.login()
        return self.as_parent(token).get(
            f"/api/v1/portal/children/{self.child.id}/attendance/{suffix}"
        )

    def test_history_summary_consumption_and_available_makeup(self):
        present = self.mark(
            self.today - datetime.timedelta(days=3),
            Attendance.Status.PRESENT,
            consumed_from_subscription=True,
            consume_outcome="consumed",
        )
        missed = self.mark(
            self.today - datetime.timedelta(days=2),
            Attendance.Status.ABSENT,
            absence_reason=Attendance.AbsenceReason.ILLNESS,
        )
        self.mark(
            self.today - datetime.timedelta(days=1),
            Attendance.Status.MAKEUP,
            consume_outcome="makeup_no_charge",
        )

        response = self.get()

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["summary"], {"present": 1, "absent": 1, "makeup": 1})
        self.assertEqual(len(response.data["results"]), 3)
        by_id = {str(row["id"]): row for row in response.data["results"]}
        self.assertTrue(by_id[str(present.id)]["consumed_from_subscription"])
        self.assertEqual(by_id[str(missed.id)]["absence_reason"], "illness")
        self.assertEqual(by_id[str(missed.id)]["group_name"], self.group.name)
        self.assertNotIn("subscription_id", by_id[str(present.id)])
        self.assertNotIn("marked_by_name", by_id[str(present.id)])

        self.assertEqual(len(response.data["available_makeups"]), 1)
        makeup = response.data["available_makeups"][0]
        self.assertEqual(str(makeup["attendance_id"]), str(missed.id))
        self.assertEqual(
            str(makeup["expires_on"]),
            str(
                self.today
                - datetime.timedelta(days=2)
                + datetime.timedelta(days=MAKEUP_EXPIRY_DAYS)
            ),
        )

    def test_period_filters_rows_and_summary_by_local_date(self):
        earlier = self.today - datetime.timedelta(days=5)
        selected = self.today - datetime.timedelta(days=1)
        self.mark(earlier, Attendance.Status.ABSENT)
        included = self.mark(selected, Attendance.Status.PRESENT)

        response = self.get(f"?date_from={selected}&date_to={selected}")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([str(row["id"]) for row in response.data["results"]], [str(included.id)])
        self.assertEqual(response.data["summary"], {"present": 1, "absent": 0, "makeup": 0})

    def test_foreign_child_is_not_disclosed(self):
        stranger = Child.objects.create(
            organization=self.org,
            full_name="Чужой ребёнок",
            birth_date=datetime.date(2018, 1, 1),
        )
        token = self.login()
        response = self.as_parent(token).get(f"/api/v1/portal/children/{stranger.id}/attendance/")
        self.assertEqual(response.status_code, 404)

    def test_invalid_period_is_rejected(self):
        date_from = self.today
        date_to = self.today - datetime.timedelta(days=1)
        response = self.get(f"?date_from={date_from}&date_to={date_to}")
        self.assertEqual(response.status_code, 400)

    def test_parent_authentication_is_required(self):
        response = self.api.get(f"/api/v1/portal/children/{self.child.id}/attendance/")
        self.assertEqual(response.status_code, 401)
