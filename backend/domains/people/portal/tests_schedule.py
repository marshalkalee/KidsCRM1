"""Parent portal schedule API."""

import datetime
from decimal import Decimal

from django.utils import timezone

from domains.money.subscriptions.models import Subscription
from domains.money.subscriptions.subscription_types import create_type
from domains.people.clients.models import Child
from domains.platform.tasks.models import Task
from domains.platform.tenants.models import Direction
from domains.scheduling.attendance.models import Attendance
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.schedule.models import Lesson, LessonEnrollment

from .models import ParentLessonRequest
from .tests_auth import PortalAuthBase


class ParentScheduleTests(PortalAuthBase):
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
        GroupMembership.objects.create(
            organization=self.org,
            group=self.group,
            child=self.child,
            joined_at=self.today,
        )

    def lesson(self, day, hour=18, *, group=True):
        starts_at = datetime.datetime.combine(day, datetime.time(hour), tzinfo=self.tz)
        lesson_group = self.group if group is True else group or None
        return Lesson.objects.create(
            organization=self.org,
            group=lesson_group,
            starts_at=starts_at,
            ends_at=starts_at + datetime.timedelta(hours=1),
        )

    def get(self, suffix=""):
        token = self.login()
        return self.as_parent(token).get(
            f"/api/v1/portal/children/{self.child.id}/schedule/{suffix}"
        )

    def test_shows_group_individual_and_extra_lessons(self):
        group_lesson = self.lesson(self.today + datetime.timedelta(days=1))
        individual = self.lesson(self.today + datetime.timedelta(days=2), group=False)
        individual.individual_children.add(self.child)
        extra = self.lesson(self.today + datetime.timedelta(days=3), group=False)
        LessonEnrollment.objects.create(
            organization=self.org,
            lesson=extra,
            child=self.child,
            kind=LessonEnrollment.Kind.MAKEUP,
        )

        response = self.get()

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["results"]), 3)
        by_id = {str(row["id"]): row for row in response.data["results"]}
        self.assertEqual(by_id[str(group_lesson.id)]["group_name"], self.group.name)
        self.assertIsNone(by_id[str(individual.id)]["enrollment_kind"])
        self.assertEqual(by_id[str(extra.id)]["enrollment_kind"], "makeup")
        self.assertNotIn("note", by_id[str(group_lesson.id)])

    def test_foreign_child_is_not_disclosed(self):
        stranger = Child.objects.create(
            organization=self.org,
            full_name="Чужой ребёнок",
            birth_date=datetime.date(2018, 1, 1),
        )
        token = self.login()
        response = self.as_parent(token).get(f"/api/v1/portal/children/{stranger.id}/schedule/")
        self.assertEqual(response.status_code, 404)

    def test_parent_authentication_is_required(self):
        response = self.api.get(f"/api/v1/portal/children/{self.child.id}/schedule/")
        self.assertEqual(response.status_code, 401)

    def test_parent_can_choose_and_request_valid_makeup_without_booking(self):
        source_lesson = self.lesson(self.today - datetime.timedelta(days=1))
        source = Attendance.objects.create(
            organization=self.org,
            lesson=source_lesson,
            child=self.child,
            status=Attendance.Status.ABSENT,
        )
        other_group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Балет 12–15",
            capacity=10,
        )
        candidate = self.lesson(self.today + datetime.timedelta(days=2), group=other_group)
        token = self.login()
        client = self.as_parent(token)
        url = f"/api/v1/portal/children/{self.child.id}/makeups/{source.id}/"

        options = client.get(url)
        self.assertEqual(options.status_code, 200, options.data)
        self.assertEqual([str(row["id"]) for row in options.data["results"]], [str(candidate.id)])

        created = client.post(
            url, {"lesson_id": str(candidate.id), "comment": "Удобно вечером"}, format="json"
        )
        self.assertEqual(created.status_code, 201, created.data)
        parent_request = ParentLessonRequest.objects.get(id=created.data["id"])
        self.assertEqual(parent_request.kind, ParentLessonRequest.Kind.MAKEUP)
        self.assertEqual(parent_request.source_attendance, source)
        self.assertEqual(parent_request.status, ParentLessonRequest.Status.NEW)
        self.assertFalse(
            LessonEnrollment.objects.filter(child=self.child, lesson=candidate).exists()
        )
        self.assertTrue(
            Task.objects.filter(
                organization=self.org,
                type=Task.Type.PARENT_REQUEST,
                source_key=f"parent-request:{parent_request.id}",
            ).exists()
        )

        repeated = client.post(url, {"lesson_id": str(candidate.id)}, format="json")
        self.assertEqual(repeated.status_code, 409)

    def test_three_requests_for_last_place_do_not_change_capacity(self):
        candidate_group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Балет последнее место",
            capacity=1,
            age_min=5,
            age_max=15,
        )
        candidate = self.lesson(self.today + datetime.timedelta(days=2), group=candidate_group)
        for index in range(3):
            _, (other_child,) = self.family_for_request(index)
            token = self.login(f"+7701888000{index}")
            response = self.as_parent(token).post(
                f"/api/v1/portal/children/{other_child.id}/lesson-requests/",
                {"type": "enroll", "lesson_id": str(candidate.id)},
                format="json",
            )
            self.assertEqual(response.status_code, 201, response.data)

        self.assertEqual(candidate.participants().count(), 0)
        self.assertEqual(ParentLessonRequest.objects.filter(lesson=candidate).count(), 3)

    def family_for_request(self, index):
        from .tests_auth import family

        phone = f"+7701888000{index}"
        _parent, children = family(self.org, f"Родитель {index}", phone, f"Ребёнок {index}")
        child = children[0]
        GroupMembership.objects.create(
            organization=self.org,
            group=self.group,
            child=child,
            joined_at=self.today,
        )
        return _parent, children

    def test_parent_can_request_cancellation_without_changing_schedule(self):
        lesson = self.lesson(self.today + datetime.timedelta(days=1))
        token = self.login()
        response = self.as_parent(token).post(
            f"/api/v1/portal/children/{self.child.id}/lesson-requests/",
            {"type": "cancel", "lesson_id": str(lesson.id), "comment": "Заболели"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], "new")
        self.assertTrue(lesson.participants().filter(id=self.child.id).exists())
        lesson.refresh_from_db()
        self.assertEqual(lesson.status, Lesson.Status.SCHEDULED)

    def test_regular_options_match_direction_age_and_capacity(self):
        suitable_group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Подходящая группа",
            capacity=2,
            age_min=5,
            age_max=15,
        )
        suitable = self.lesson(self.today + datetime.timedelta(days=2), group=suitable_group)
        too_old_group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Только малыши",
            capacity=2,
            age_min=2,
            age_max=3,
        )
        self.lesson(self.today + datetime.timedelta(days=2), hour=17, group=too_old_group)
        other_direction = Direction.objects.create(organization=self.org, name="Рисование")
        wrong_direction_group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=other_direction,
            name="Другое направление",
            capacity=2,
        )
        self.lesson(self.today + datetime.timedelta(days=2), hour=16, group=wrong_direction_group)
        full_group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Полная группа",
            capacity=1,
        )
        full_lesson = self.lesson(self.today + datetime.timedelta(days=3), group=full_group)
        stranger = Child.objects.create(
            organization=self.org,
            full_name="Занял место",
            birth_date=datetime.date(2017, 1, 1),
        )
        GroupMembership.objects.create(
            organization=self.org,
            group=full_group,
            child=stranger,
            joined_at=self.today,
        )

        response = self.as_parent(self.login()).get(
            f"/api/v1/portal/children/{self.child.id}/lesson-request-options/"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([row["id"] for row in response.data["results"]], [str(suitable.id)])
        self.assertEqual(full_lesson.participants().count(), 1)

    def test_makeup_uses_subscription_window_and_limit(self):
        subscription_type = create_type(
            self.org,
            name="С отработкой",
            price=Decimal("30000"),
            quota_sessions=8,
            duration_days=30,
            rules={"makeup_window_days": 30, "makeups_limit": 1},
            directions=[self.direction],
            branches=[self.branch],
        )
        version = subscription_type.versions.get()
        Subscription.objects.create(
            organization=self.org,
            child=self.child,
            subscription_type_version=version,
            direction=self.direction,
            branch=self.branch,
            starts_on=self.today - datetime.timedelta(days=25),
            ends_on=self.today + datetime.timedelta(days=5),
            sessions_remaining_cache=5,
            list_price=Decimal("30000"),
            price=Decimal("30000"),
        )
        source_lesson = self.lesson(self.today - datetime.timedelta(days=20))
        source = Attendance.objects.create(
            organization=self.org,
            lesson=source_lesson,
            child=self.child,
            status=Attendance.Status.ABSENT,
        )
        candidate_group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Отработка",
            capacity=10,
        )
        candidate = self.lesson(self.today + datetime.timedelta(days=2), group=candidate_group)
        client = self.as_parent(self.login())
        url = f"/api/v1/portal/children/{self.child.id}/makeups/{source.id}/"
        self.assertEqual(client.get(url).status_code, 200)  # 20 дней допустимы правилом типа

        used_source_lesson = self.lesson(self.today - datetime.timedelta(days=10), hour=17)
        used_source = Attendance.objects.create(
            organization=self.org,
            lesson=used_source_lesson,
            child=self.child,
            status=Attendance.Status.ABSENT,
        )
        LessonEnrollment.objects.create(
            organization=self.org,
            lesson=candidate,
            child=self.child,
            kind=LessonEnrollment.Kind.MAKEUP,
            source_attendance=used_source,
        )
        self.assertEqual(client.get(url).status_code, 409)  # лимит 1 уже использован

    def test_makeup_rejects_foreign_child(self):
        source_lesson = self.lesson(self.today - datetime.timedelta(days=1))
        source = Attendance.objects.create(
            organization=self.org,
            lesson=source_lesson,
            child=self.child,
            status=Attendance.Status.ABSENT,
        )
        stranger = Child.objects.create(
            organization=self.org,
            full_name="Чужой ребёнок",
            birth_date=datetime.date(2018, 1, 1),
        )
        token = self.login()
        response = self.as_parent(token).get(
            f"/api/v1/portal/children/{stranger.id}/makeups/{source.id}/"
        )
        self.assertEqual(response.status_code, 404)
