import datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from domains.people.clients.models import Child
from domains.platform.tenants.models import Branch, Direction, Organization, Room
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.schedule.models import Lesson

User = get_user_model()


class LessonStatusTransitionTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.branch = Branch.objects.create(organization=self.org, name="Главный")
        self.direction = Direction.objects.create(organization=self.org, name="Балет")
        self.group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Балет — Младшая",
            capacity=12,
        )
        tz = timezone.zoneinfo.ZoneInfo("Asia/Almaty")
        self.starts_at = datetime.datetime(2026, 9, 18, 19, 0, tzinfo=tz)
        self.ends_at = datetime.datetime(2026, 9, 18, 20, 0, tzinfo=tz)
        self.lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            starts_at=self.starts_at,
            ends_at=self.ends_at,
        )

    def test_lesson_created_as_scheduled(self):
        self.assertEqual(self.lesson.status, Lesson.Status.SCHEDULED)

    def test_transition_scheduled_to_completed(self):
        self.lesson.transition_to(Lesson.Status.COMPLETED)
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, Lesson.Status.COMPLETED)

    def test_transition_scheduled_to_cancelled(self):
        self.lesson.transition_to(Lesson.Status.CANCELLED)
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, Lesson.Status.CANCELLED)

    def test_transition_completed_to_cancelled_forbidden(self):
        self.lesson.transition_to(Lesson.Status.COMPLETED)
        with self.assertRaises(ValidationError):
            self.lesson.transition_to(Lesson.Status.CANCELLED)

    def test_reschedule_links_lessons(self):
        new_lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            starts_at=self.starts_at + datetime.timedelta(days=7),
            ends_at=self.ends_at + datetime.timedelta(days=7),
        )
        self.lesson.reschedule_to(new_lesson)
        self.lesson.refresh_from_db()
        new_lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, Lesson.Status.RESCHEDULED)
        self.assertEqual(new_lesson.rescheduled_from, self.lesson)

    def test_evening_lesson_in_almaty_timezone(self):
        tz = timezone.zoneinfo.ZoneInfo("Asia/Almaty")
        starts_at = datetime.datetime(2026, 9, 18, 19, 0, tzinfo=tz)
        lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            starts_at=starts_at,
            ends_at=starts_at + datetime.timedelta(hours=1),
        )
        local_date = lesson.starts_at.astimezone(tz).date()
        self.assertEqual(local_date, datetime.date(2026, 9, 18))
        utc_date = lesson.starts_at.date()
        self.assertEqual(utc_date, datetime.date(2026, 9, 18))

    def test_tenant_isolation(self):
        org2 = Organization.objects.create(name="Other", slug="other")
        self.assertEqual(Lesson.objects.for_tenant(org2).count(), 0)


def _authenticated_client(user):
    # LessonViewSet берёт организацию из claim'а JWT через TenantMiddleware
    # (request.organization), а не из request.user.organization — обычный
    # force_authenticate() не создаёт заголовок Authorization, поэтому
    # middleware его не видит и request.organization остаётся None (см.
    # тот же паттерн в tests_rbac.py: make_client()).
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    refresh["organization_id"] = str(user.organization_id)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


class LessonCalendarApiTest(APITestCase):
    """
    Календарь (TRU-44): один запрос на весь диапазон дат, без запроса на
    занятие (ТЗ п. 10.2 — ≤ 1с при 500 занятиях в неделю).
    """

    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.branch = Branch.objects.create(organization=self.org, name="Главный")
        self.direction = Direction.objects.create(
            organization=self.org, name="Балет", color="#AA00FF"
        )
        self.group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Балет — Младшая",
            capacity=12,
        )
        self.teacher = User.objects.create_user(
            phone="+77010000010",
            full_name="Преподаватель",
            password="pass12345",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        self.owner = User.objects.create_user(
            phone="+77010000011",
            full_name="Владелец",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )
        for i in range(3):
            child = Child.objects.create(
                organization=self.org,
                full_name=f"Ребёнок {i}",
                birth_date=datetime.date.today() - datetime.timedelta(days=365 * 7),
                gender=Child.Gender.FEMALE,
            )
            GroupMembership.objects.create(
                organization=self.org,
                group=self.group,
                child=child,
                joined_at=datetime.date.today(),
            )

        tz = timezone.zoneinfo.ZoneInfo("Asia/Almaty")
        self.week_start = datetime.datetime(2026, 9, 21, 9, 0, tzinfo=tz)
        for i in range(20):
            self._create_lesson(i)

    def _create_lesson(self, i):
        # day = i % 7 держит занятие внутри одной из 7 дней недели, час
        # растёт с i // 7 (а не с i целиком) — иначе при большом i
        # (как в тесте на 60 занятий) время «утекает» на день/два вперёд
        # и часть занятий выпадает за date_to недели.
        day = i % 7
        hour = i // 7
        return Lesson.objects.create(
            organization=self.org,
            group=self.group,
            teacher=self.teacher,
            starts_at=self.week_start + datetime.timedelta(days=day, hours=hour),
            ends_at=self.week_start + datetime.timedelta(days=day, hours=hour + 1),
        )

    def test_week_range_returns_calendar_fields_without_pagination(self):
        client = _authenticated_client(self.owner)

        response = client.get(
            "/api/v1/schedule/",
            {"date_from": "2026-09-21", "date_to": "2026-09-27"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertEqual(len(response.data), 20)
        lesson = response.data[0]
        self.assertEqual(lesson["direction_color"], "#AA00FF")
        self.assertEqual(lesson["group_name"], "Балет — Младшая")
        self.assertEqual(lesson["capacity"], 12)
        self.assertEqual(lesson["enrolled_count"], 3)
        self.assertEqual(lesson["teacher_name"], "Преподаватель")

    def test_query_count_does_not_grow_with_lesson_count(self):
        client = _authenticated_client(self.owner)
        params = {"date_from": "2026-09-21", "date_to": "2026-09-27"}

        with CaptureQueriesContext(connection) as small:
            client.get("/api/v1/schedule/", params)

        # Ещё занятия в том же диапазоне — число запросов не должно расти.
        for i in range(20, 60):
            self._create_lesson(i)

        with CaptureQueriesContext(connection) as large:
            response = client.get("/api/v1/schedule/", params)

        self.assertEqual(len(response.data), 60)
        self.assertEqual(len(small.captured_queries), len(large.captured_queries))


class LessonCalendarFiltersTest(APITestCase):
    """
    Фильтры и режим преподавателя (TRU-45).
    """

    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.branch_a = Branch.objects.create(organization=self.org, name="Центр")
        self.branch_b = Branch.objects.create(organization=self.org, name="Юг")
        self.room_a = Room.objects.create(branch=self.branch_a, name="Зал 1")
        self.room_b = Room.objects.create(branch=self.branch_b, name="Зал 2")
        self.direction_ballet = Direction.objects.create(organization=self.org, name="Балет")
        self.direction_vocal = Direction.objects.create(organization=self.org, name="Вокал")
        self.group_ballet = Group.objects.create(
            organization=self.org,
            branch=self.branch_a,
            direction=self.direction_ballet,
            name="Балет",
            capacity=10,
        )
        self.group_vocal = Group.objects.create(
            organization=self.org,
            branch=self.branch_b,
            direction=self.direction_vocal,
            name="Вокал",
            capacity=10,
        )
        self.teacher_a = User.objects.create_user(
            phone="+77020000001",
            full_name="Айгуль",
            password="pass12345",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        self.teacher_b = User.objects.create_user(
            phone="+77020000002",
            full_name="Бекзат",
            password="pass12345",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        self.owner = User.objects.create_user(
            phone="+77020000003",
            full_name="Владелец",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )

        tz = timezone.zoneinfo.ZoneInfo("Asia/Almaty")
        day = datetime.datetime(2026, 9, 24, 10, 0, tzinfo=tz)
        self.lesson_a = Lesson.objects.create(
            organization=self.org,
            group=self.group_ballet,
            room=self.room_a,
            teacher=self.teacher_a,
            starts_at=day,
            ends_at=day + datetime.timedelta(hours=1),
        )
        self.lesson_b = Lesson.objects.create(
            organization=self.org,
            group=self.group_vocal,
            room=self.room_b,
            teacher=self.teacher_b,
            starts_at=day + datetime.timedelta(hours=2),
            ends_at=day + datetime.timedelta(hours=3),
        )
        self.params = {"date_from": "2026-09-24", "date_to": "2026-09-24"}

    def test_room_filter(self):
        client = _authenticated_client(self.owner)
        response = client.get("/api/v1/schedule/", {**self.params, "room": self.room_a.id})
        ids = {row["id"] for row in response.data}
        self.assertEqual(ids, {str(self.lesson_a.id)})

    def test_direction_filter(self):
        client = _authenticated_client(self.owner)
        response = client.get(
            "/api/v1/schedule/", {**self.params, "direction": self.direction_vocal.id}
        )
        ids = {row["id"] for row in response.data}
        self.assertEqual(ids, {str(self.lesson_b.id)})

    def test_branch_filter_matches_individual_lesson_via_room(self):
        # Индивидуальное занятие без группы — филиал берётся из зала.
        tz = timezone.zoneinfo.ZoneInfo("Asia/Almaty")
        solo = Lesson.objects.create(
            organization=self.org,
            room=self.room_b,
            starts_at=datetime.datetime(2026, 9, 24, 15, 0, tzinfo=tz),
            ends_at=datetime.datetime(2026, 9, 24, 16, 0, tzinfo=tz),
        )
        client = _authenticated_client(self.owner)
        response = client.get("/api/v1/schedule/", {**self.params, "branch": self.branch_b.id})
        ids = {row["id"] for row in response.data}
        self.assertEqual(ids, {str(self.lesson_b.id), str(solo.id)})

    def test_teacher_sees_only_own_lessons_without_filtering(self):
        client = _authenticated_client(self.teacher_a)
        response = client.get("/api/v1/schedule/", self.params)
        ids = {row["id"] for row in response.data}
        self.assertEqual(ids, {str(self.lesson_a.id)})

    def test_teacher_filter_is_ignored_for_teacher_role(self):
        # Даже если преподаватель явно запросит чужой teacher=,
        # бэкенд всё равно отдаёт только его собственные занятия.
        client = _authenticated_client(self.teacher_a)
        response = client.get("/api/v1/schedule/", {**self.params, "teacher": self.teacher_b.id})
        ids = {row["id"] for row in response.data}
        self.assertEqual(ids, {str(self.lesson_a.id)})

    def test_owner_can_filter_by_any_teacher(self):
        client = _authenticated_client(self.owner)
        response = client.get("/api/v1/schedule/", {**self.params, "teacher": self.teacher_b.id})
        ids = {row["id"] for row in response.data}
        self.assertEqual(ids, {str(self.lesson_b.id)})


class LessonConflictTest(APITestCase):
    """
    Детект конфликтов (TRU-46, ТЗ п. 4.2): один зал/преподаватель с
    пересекающимся временем — предупреждение (409 + список конфликтов),
    не запрет — confirm_conflict: true сохраняет всё равно.
    """

    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.branch = Branch.objects.create(organization=self.org, name="Главный")
        self.room = Room.objects.create(branch=self.branch, name="Зал 1")
        self.other_room = Room.objects.create(branch=self.branch, name="Зал 2")
        self.direction = Direction.objects.create(organization=self.org, name="Балет")
        self.group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Балет",
            capacity=10,
        )
        self.teacher = User.objects.create_user(
            phone="+77040000001",
            full_name="Айгуль",
            password="pass12345",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        self.other_teacher = User.objects.create_user(
            phone="+77040000002",
            full_name="Бекзат",
            password="pass12345",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        self.owner = User.objects.create_user(
            phone="+77040000003",
            full_name="Владелец",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )
        tz = timezone.zoneinfo.ZoneInfo("Asia/Almaty")
        self.day = datetime.datetime(2026, 9, 24, 18, 0, tzinfo=tz)
        self.existing = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            room=self.room,
            teacher=self.teacher,
            starts_at=self.day,
            ends_at=self.day + datetime.timedelta(hours=1),
        )

    def _overlapping_payload(self, **overrides):
        payload = {
            "group": str(self.group.id),
            "room": str(self.room.id),
            "starts_at": self.day.isoformat(),
            "ends_at": (self.day + datetime.timedelta(hours=1)).isoformat(),
        }
        payload.update(overrides)
        return payload

    def test_create_with_room_conflict_returns_409_without_confirm(self):
        client = _authenticated_client(self.owner)

        response = client.post("/api/v1/schedule/", self._overlapping_payload(), format="json")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertTrue(response.data["conflict"])
        conflict_ids = {c["id"] for c in response.data["conflicts"]}
        self.assertEqual(conflict_ids, {str(self.existing.id)})
        # Не сохранилось — предупреждение, а не тихий сейв.
        self.assertEqual(Lesson.objects.for_tenant(self.org).count(), 1)

    def test_create_with_confirm_conflict_saves_anyway(self):
        client = _authenticated_client(self.owner)

        response = client.post(
            "/api/v1/schedule/",
            self._overlapping_payload(confirm_conflict=True),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Lesson.objects.for_tenant(self.org).count(), 2)

    def test_teacher_conflict_in_different_rooms_still_detected(self):
        client = _authenticated_client(self.owner)

        response = client.post(
            "/api/v1/schedule/",
            self._overlapping_payload(room=str(self.other_room.id), teacher=str(self.teacher.id)),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_non_overlapping_time_has_no_conflict(self):
        client = _authenticated_client(self.owner)
        later = self.day + datetime.timedelta(hours=2)

        response = client.post(
            "/api/v1/schedule/",
            self._overlapping_payload(
                starts_at=later.isoformat(),
                ends_at=(later + datetime.timedelta(hours=1)).isoformat(),
            ),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_cancelled_existing_lesson_does_not_block(self):
        self.existing.transition_to(Lesson.Status.CANCELLED)
        client = _authenticated_client(self.owner)

        response = client.post("/api/v1/schedule/", self._overlapping_payload(), format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_individual_lesson_without_group_counts_as_conflict(self):
        client = _authenticated_client(self.owner)
        payload = self._overlapping_payload()
        del payload["group"]

        response = client.post("/api/v1/schedule/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_reschedule_detects_conflict_and_confirms(self):
        other = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            room=self.room,
            starts_at=self.day + datetime.timedelta(days=1),
            ends_at=self.day + datetime.timedelta(days=1, hours=1),
        )
        client = _authenticated_client(self.owner)

        response = client.post(
            f"/api/v1/schedule/{other.id}/reschedule/",
            {
                "group": str(self.group.id),
                "room": str(self.room.id),
                "starts_at": self.day.isoformat(),
                "ends_at": (self.day + datetime.timedelta(hours=1)).isoformat(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        other.refresh_from_db()
        self.assertEqual(other.status, Lesson.Status.SCHEDULED)  # ещё не перенесено

        response = client.post(
            f"/api/v1/schedule/{other.id}/reschedule/",
            {
                "group": str(self.group.id),
                "room": str(self.room.id),
                "starts_at": self.day.isoformat(),
                "ends_at": (self.day + datetime.timedelta(hours=1)).isoformat(),
                "confirm_conflict": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        other.refresh_from_db()
        self.assertEqual(other.status, Lesson.Status.RESCHEDULED)

    def test_update_moving_lesson_into_conflict_is_blocked_without_confirm(self):
        other = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            room=self.room,
            starts_at=self.day + datetime.timedelta(days=1),
            ends_at=self.day + datetime.timedelta(days=1, hours=1),
        )
        client = _authenticated_client(self.owner)

        response = client.patch(
            f"/api/v1/schedule/{other.id}/",
            {
                "starts_at": self.day.isoformat(),
                "ends_at": (self.day + datetime.timedelta(hours=1)).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        other.refresh_from_db()
        self.assertEqual(other.starts_at, self.day + datetime.timedelta(days=1))

    def test_update_without_moving_out_of_own_slot_does_not_self_conflict(self):
        # Изменение заметки у self.existing не должно "конфликтовать само с
        # собой" — exclude_id обязателен при апдейте.
        client = _authenticated_client(self.owner)

        response = client.patch(
            f"/api/v1/schedule/{self.existing.id}/", {"note": "новая заметка"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_calendar_list_marks_conflicting_lessons(self):
        second = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            room=self.room,
            starts_at=self.day + datetime.timedelta(minutes=30),
            ends_at=self.day + datetime.timedelta(minutes=90),
        )
        unrelated = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            room=self.other_room,
            starts_at=self.day + datetime.timedelta(hours=5),
            ends_at=self.day + datetime.timedelta(hours=6),
        )
        client = _authenticated_client(self.owner)

        response = client.get(
            "/api/v1/schedule/", {"date_from": "2026-09-24", "date_to": "2026-09-24"}
        )

        by_id = {row["id"]: row for row in response.data}
        self.assertTrue(by_id[str(self.existing.id)]["has_conflict"])
        self.assertTrue(by_id[str(second.id)]["has_conflict"])
        self.assertEqual(
            set(by_id[str(self.existing.id)]["conflicting_lesson_ids"]), {str(second.id)}
        )
        self.assertFalse(by_id[str(unrelated.id)]["has_conflict"])

    def test_conflicts_endpoint_lists_only_conflicting_lessons(self):
        second = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            room=self.room,
            starts_at=self.day + datetime.timedelta(minutes=30),
            ends_at=self.day + datetime.timedelta(minutes=90),
        )
        Lesson.objects.create(
            organization=self.org,
            group=self.group,
            room=self.other_room,
            starts_at=self.day + datetime.timedelta(hours=5),
            ends_at=self.day + datetime.timedelta(hours=6),
        )
        client = _authenticated_client(self.owner)

        response = client.get(
            "/api/v1/schedule/conflicts/", {"date_from": "2026-09-24", "date_to": "2026-09-24"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in response.data}
        self.assertEqual(ids, {str(self.existing.id), str(second.id)})
