from datetime import date, time, timedelta

from rest_framework.test import APITestCase

from domains.people.clients.models import Child
from domains.platform.core.utils import today_for_org
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.tenants.org_settings import GROUP_UNDERFILLED_PERCENT_THRESHOLD
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.schedule_templates.models import ScheduleTemplate, ScheduleTemplateSlot

URL = "/api/v1/analytics/group-occupancy/"


class GroupOccupancyApiTests(APITestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Центр",
            slug="occupancy-report",
            settings={GROUP_UNDERFILLED_PERCENT_THRESHOLD: 50},
        )
        self.branch = Branch.objects.create(organization=self.organization, name="Абая")
        self.direction = Direction.objects.create(organization=self.organization, name="Балет")
        self.teacher = User.objects.create_user(
            organization=self.organization,
            phone="+77015550119",
            password="x",
            full_name="Анна Петрова",
            role=User.Role.TEACHER,
        )
        self.owner = User.objects.create_user(
            organization=self.organization,
            phone="+77015550120",
            password="x",
            full_name="Владелец",
            role=User.Role.OWNER,
        )
        self.small = self.group("Младшая", capacity=10, members=4, weekday=2, starts=time(10))
        self.large = self.group("Старшая", capacity=10, members=8, weekday=0, starts=time(18))
        self.client.force_authenticate(self.owner)

    def group(self, name, *, capacity, members, weekday, starts):
        group = Group.objects.create(
            organization=self.organization,
            branch=self.branch,
            direction=self.direction,
            name=name,
            capacity=capacity,
        )
        group.teachers.add(self.teacher)
        today = today_for_org(self.organization)
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
                joined_at=today - timedelta(days=40),
            )
        template = ScheduleTemplate.objects.create(
            organization=self.organization,
            group=group,
            valid_from=today - timedelta(days=60),
        )
        ScheduleTemplateSlot.objects.create(
            organization=self.organization,
            template=template,
            weekday=weekday,
            start_time=starts,
            teacher=self.teacher,
        )
        return group

    def test_current_values_match_groups_screen_and_threshold(self):
        response = self.client.get(URL, {"period": "year"})
        self.assertEqual(response.status_code, 200)
        data = response.data
        self.assertEqual(
            data["summary"],
            {
                "groups_count": 2,
                "occupied": 12,
                "capacity": 20,
                "percent": 60.0,
                "underfilled_count": 1,
            },
        )
        self.assertEqual(
            [(row["name"], row["percent"]) for row in data["groups"]],
            [("Младшая", 40), ("Старшая", 80)],
        )
        self.assertEqual([row["name"] for row in data["underfilled"]], ["Младшая"])
        group_screen = self.client.get("/api/v1/groups/").data
        group_screen = group_screen.get("results", group_screen)
        self.assertEqual(
            {row["name"]: row["fill_percent"] for row in group_screen},
            {row["name"]: row["percent"] for row in data["groups"]},
        )

        self.organization.settings[GROUP_UNDERFILLED_PERCENT_THRESHOLD] = 90
        self.organization.save(update_fields=["settings"])
        changed = self.client.get(URL).data
        self.assertEqual(changed["threshold"], 90)
        self.assertEqual(changed["summary"]["underfilled_count"], 2)

    def test_weekday_time_teacher_and_direction_filters(self):
        wednesday = self.client.get(URL, {"weekday": "2"}).data
        self.assertEqual([row["name"] for row in wednesday["groups"]], ["Младшая"])
        evening = self.client.get(URL, {"time": "evening"}).data
        self.assertEqual([row["name"] for row in evening["groups"]], ["Старшая"])
        teacher = self.client.get(URL, {"teacher": str(self.teacher.id)}).data
        self.assertEqual(teacher["summary"]["groups_count"], 2)
        direction = self.client.get(URL, {"direction": str(self.direction.id)}).data
        self.assertEqual(direction["summary"]["groups_count"], 2)

    def test_monthly_trend_and_excel_export(self):
        data = self.client.get(URL, {"period": "year"}).data
        self.assertGreaterEqual(len(data["trend"]), 1)
        self.assertEqual(data["trend"][-1]["value"], 60.0)

        export = self.client.get(
            "/api/v1/analytics/export/", {"report": "group_occupancy", "period": "year"}
        )
        self.assertEqual(export.status_code, 200)
        self.assertEqual(
            export["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertTrue(export.content.startswith(b"PK"))
