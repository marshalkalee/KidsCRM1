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

from domains.money.subscriptions.models import (
    LessonConsumption,
    Subscription,
    SubscriptionLedgerEntry,
)
from domains.money.subscriptions.subscription_service import SubscriptionService
from domains.money.subscriptions.subscription_types import create_type
from domains.money.subscriptions.subscriptions import add_ledger_entry
from domains.people.clients.models import Child
from domains.platform.core.audit import AuditLog
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
        self.child = Child.objects.create(
            organization=self.org,
            full_name="Соло Солистова",
            birth_date=datetime.date.today() - datetime.timedelta(days=365 * 10),
            gender=Child.Gender.FEMALE,
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
        payload = self._overlapping_payload(individual_children=[str(self.child.id)])
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


class IndividualLessonTest(APITestCase):
    """
    Индивидуальные занятия (TRU-47, ТЗ п. 4.2): создание вне группы, с
    привязкой ребёнка (или нескольких), отличимы в календаре, участвуют в
    проверке конфликтов наравне с групповыми.
    """

    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.branch = Branch.objects.create(organization=self.org, name="Главный")
        self.room = Room.objects.create(branch=self.branch, name="Зал 1")
        self.direction = Direction.objects.create(organization=self.org, name="Балет")
        self.group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Балет",
            capacity=10,
        )
        self.teacher = User.objects.create_user(
            phone="+77050000001",
            full_name="Айгуль",
            password="pass12345",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        self.owner = User.objects.create_user(
            phone="+77050000002",
            full_name="Владелец",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.child = Child.objects.create(
            organization=self.org,
            full_name="Соло Солистова",
            birth_date=datetime.date.today() - datetime.timedelta(days=365 * 10),
            gender=Child.Gender.FEMALE,
        )
        self.other_child = Child.objects.create(
            organization=self.org,
            full_name="Дуэт Дуэтова",
            birth_date=datetime.date.today() - datetime.timedelta(days=365 * 11),
            gender=Child.Gender.FEMALE,
        )
        foreign_org = Organization.objects.create(name="Другая студия", slug="other")
        self.foreign_child = Child.objects.create(
            organization=foreign_org,
            full_name="Чужой Ребёнок",
            birth_date=datetime.date.today() - datetime.timedelta(days=365 * 9),
            gender=Child.Gender.MALE,
        )
        tz = timezone.zoneinfo.ZoneInfo("Asia/Almaty")
        self.day = datetime.datetime(2026, 9, 24, 17, 0, tzinfo=tz)

    def _payload(self, **overrides):
        payload = {
            "room": str(self.room.id),
            "teacher": str(self.teacher.id),
            "individual_children": [str(self.child.id)],
            "starts_at": self.day.isoformat(),
            "ends_at": (self.day + datetime.timedelta(hours=1)).isoformat(),
        }
        payload.update(overrides)
        return payload

    def test_create_individual_lesson_with_one_child(self):
        client = _authenticated_client(self.owner)

        response = client.post("/api/v1/schedule/", self._payload(), format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertTrue(response.data["is_individual"])
        self.assertIsNone(response.data["group"])
        self.assertEqual(response.data["individual_children_names"], ["Соло Солистова"])
        lesson = Lesson.objects.get(pk=response.data["id"])
        self.assertEqual(list(lesson.individual_children.all()), [self.child])

    def test_create_individual_lesson_with_several_children(self):
        client = _authenticated_client(self.owner)

        response = client.post(
            "/api/v1/schedule/",
            self._payload(individual_children=[str(self.child.id), str(self.other_child.id)]),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        lesson = Lesson.objects.get(pk=response.data["id"])
        self.assertEqual(lesson.individual_children.count(), 2)

    def test_individual_lesson_requires_at_least_one_child(self):
        client = _authenticated_client(self.owner)

        response = client.post(
            "/api/v1/schedule/", self._payload(individual_children=[]), format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("individual_children", response.data)

    def test_group_lesson_cannot_also_have_individual_children(self):
        client = _authenticated_client(self.owner)

        response = client.post(
            "/api/v1/schedule/",
            self._payload(group=str(self.group.id)),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("individual_children", response.data)

    def test_cannot_attach_child_from_another_organization(self):
        client = _authenticated_client(self.owner)

        response = client.post(
            "/api/v1/schedule/",
            self._payload(individual_children=[str(self.foreign_child.id)]),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("individual_children", response.data)

    def test_individual_lesson_visible_in_calendar_distinguishable_from_group(self):
        client = _authenticated_client(self.owner)
        client.post("/api/v1/schedule/", self._payload(), format="json")
        Lesson.objects.create(
            organization=self.org,
            group=self.group,
            room=self.room,
            starts_at=self.day + datetime.timedelta(hours=3),
            ends_at=self.day + datetime.timedelta(hours=4),
        )

        response = client.get(
            "/api/v1/schedule/", {"date_from": "2026-09-24", "date_to": "2026-09-24"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        individual = next(row for row in response.data if row["is_individual"])
        group_lesson = next(row for row in response.data if not row["is_individual"])
        self.assertEqual(individual["individual_children_names"], ["Соло Солистова"])
        self.assertIsNone(individual["group_name"])
        self.assertEqual(group_lesson["group_name"], "Балет")

    def test_individual_lesson_participates_in_room_conflict(self):
        Lesson.objects.create(
            organization=self.org,
            group=self.group,
            room=self.room,
            starts_at=self.day,
            ends_at=self.day + datetime.timedelta(hours=1),
        )
        client = _authenticated_client(self.owner)

        response = client.post("/api/v1/schedule/", self._payload(), format="json")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_individual_lesson_participates_in_teacher_conflict(self):
        # Существующее занятие в ДРУГОМ зале, но с тем же преподавателем —
        # конфликт должен сработать по teacher, не по room.
        other_room = Room.objects.create(branch=self.branch, name="Зал 2")
        Lesson.objects.create(
            organization=self.org,
            group=self.group,
            room=other_room,
            teacher=self.teacher,
            starts_at=self.day,
            ends_at=self.day + datetime.timedelta(hours=1),
        )
        client = _authenticated_client(self.owner)

        # _payload() по умолчанию — self.room (не other_room) и self.teacher.
        response = client.post("/api/v1/schedule/", self._payload(), format="json")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_participants_returns_individual_children(self):
        lesson = Lesson.objects.create(
            organization=self.org,
            room=self.room,
            teacher=self.teacher,
            starts_at=self.day,
            ends_at=self.day + datetime.timedelta(hours=1),
        )
        lesson.individual_children.set([self.child, self.other_child])

        participants = list(lesson.participants())

        self.assertEqual(set(participants), {self.child, self.other_child})
        self.assertTrue(lesson.is_individual)

    def test_participants_returns_active_group_members_for_group_lesson(self):
        left_child = Child.objects.create(
            organization=self.org,
            full_name="Ушедший Ребёнок",
            birth_date=datetime.date.today() - datetime.timedelta(days=365 * 8),
            gender=Child.Gender.MALE,
        )
        GroupMembership.objects.create(
            organization=self.org,
            group=self.group,
            child=self.child,
            joined_at=datetime.date.today(),
        )
        GroupMembership.objects.create(
            organization=self.org,
            group=self.group,
            child=left_child,
            joined_at=datetime.date.today() - datetime.timedelta(days=30),
            left_at=datetime.date.today() - datetime.timedelta(days=1),
        )
        lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            starts_at=self.day,
            ends_at=self.day + datetime.timedelta(hours=1),
        )

        participants = list(lesson.participants())

        self.assertEqual(participants, [self.child])
        self.assertFalse(lesson.is_individual)

    def test_reschedule_individual_lesson_preserves_children(self):
        lesson = Lesson.objects.create(
            organization=self.org,
            room=self.room,
            teacher=self.teacher,
            starts_at=self.day,
            ends_at=self.day + datetime.timedelta(hours=1),
        )
        lesson.individual_children.set([self.child])
        client = _authenticated_client(self.owner)

        response = client.post(
            f"/api/v1/schedule/{lesson.id}/reschedule/",
            {
                "room": str(self.room.id),
                "teacher": str(self.teacher.id),
                "individual_children": [str(self.child.id)],
                "starts_at": (self.day + datetime.timedelta(days=1)).isoformat(),
                "ends_at": (self.day + datetime.timedelta(days=1, hours=1)).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        new_lesson = Lesson.objects.get(pk=response.data["id"])
        self.assertEqual(list(new_lesson.individual_children.all()), [self.child])


class CancelWithReasonTest(APITestCase):
    """
    Отмена занятия с причиной (TRU-48, ТЗ п. 4.2/4.3): причина из
    справочника обязательна на уровне API; отменённое занятие остаётся
    видно в календаре; действие пишется в аудит-лог; отмена задним числом
    откатывает уже произведённые списания с абонементов.
    """

    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.branch = Branch.objects.create(organization=self.org, name="Главный")
        self.room = Room.objects.create(branch=self.branch, name="Зал 1")
        self.direction = Direction.objects.create(organization=self.org, name="Балет")
        self.group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Балет",
            capacity=10,
        )
        self.teacher = User.objects.create_user(
            phone="+77060000001",
            full_name="Айгуль",
            password="pass12345",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        self.owner = User.objects.create_user(
            phone="+77060000002",
            full_name="Владелец",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.child = Child.objects.create(
            organization=self.org,
            full_name="Балерина Иванова",
            birth_date=datetime.date.today() - datetime.timedelta(days=365 * 8),
            gender=Child.Gender.FEMALE,
        )
        GroupMembership.objects.create(
            organization=self.org,
            group=self.group,
            child=self.child,
            joined_at=datetime.date.today() - datetime.timedelta(days=60),
        )
        tz = timezone.zoneinfo.ZoneInfo("Asia/Almaty")
        self.day = datetime.datetime(2026, 9, 24, 18, 0, tzinfo=tz)
        self.lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            room=self.room,
            teacher=self.teacher,
            starts_at=self.day,
            ends_at=self.day + datetime.timedelta(hours=1),
        )

    def test_cancel_without_reason_category_is_rejected(self):
        client = _authenticated_client(self.owner)

        response = client.post(f"/api/v1/schedule/{self.lesson.id}/cancel/", {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("reason_category", response.data)
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, Lesson.Status.SCHEDULED)

    def test_cancel_with_unknown_category_is_rejected(self):
        client = _authenticated_client(self.owner)

        response = client.post(
            f"/api/v1/schedule/{self.lesson.id}/cancel/",
            {"reason_category": "bad_weather"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cancel_with_other_category_requires_comment(self):
        client = _authenticated_client(self.owner)

        response = client.post(
            f"/api/v1/schedule/{self.lesson.id}/cancel/",
            {"reason_category": "other"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("comment", response.data)

    def test_cancel_with_valid_category_succeeds(self):
        client = _authenticated_client(self.owner)

        response = client.post(
            f"/api/v1/schedule/{self.lesson.id}/cancel/",
            {"reason_category": "holiday"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["status"], "cancelled")
        self.assertEqual(response.data["cancel_reason_category"], "holiday")
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, Lesson.Status.CANCELLED)
        self.assertTrue(self.lesson.is_modified)

    def test_cancelled_lesson_remains_visible_in_calendar(self):
        client = _authenticated_client(self.owner)
        client.post(
            f"/api/v1/schedule/{self.lesson.id}/cancel/",
            {"reason_category": "holiday"},
            format="json",
        )

        response = client.get(
            "/api/v1/schedule/", {"date_from": "2026-09-24", "date_to": "2026-09-24"}
        )

        ids = {row["id"]: row for row in response.data}
        self.assertIn(str(self.lesson.id), ids)
        self.assertEqual(ids[str(self.lesson.id)]["status"], "cancelled")

    def test_audit_log_entry_recorded_on_cancel(self):
        client = _authenticated_client(self.owner)

        client.post(
            f"/api/v1/schedule/{self.lesson.id}/cancel/",
            {"reason_category": "teacher_illness", "comment": "Айгуль заболела"},
            format="json",
        )

        entry = AuditLog.objects.get(object_id=self.lesson.id)
        self.assertEqual(entry.actor, self.owner)
        self.assertEqual(entry.action, AuditLog.Action.CANCEL)
        self.assertEqual(entry.before["status"], "scheduled")
        self.assertEqual(entry.after["status"], "cancelled")
        self.assertEqual(entry.after["cancel_reason_category"], "teacher_illness")

    def test_retroactive_cancel_reverts_subscription_consumption(self):
        subscription_type = create_type(
            self.org,
            name="8 занятий",
            price=25000,
            quota_sessions=8,
            duration_days=30,
            directions=[self.direction],
        )
        subscription = Subscription.objects.create(
            organization=self.org,
            child=self.child,
            subscription_type_version=subscription_type.versions.latest(),
            direction=self.direction,
            starts_on=datetime.date.today(),
            ends_on=datetime.date.today() + datetime.timedelta(days=30),
            list_price=25000,
            price=25000,
        )
        add_ledger_entry(subscription, kind=SubscriptionLedgerEntry.Kind.INITIAL_GRANT, delta=8)
        # Занятие уже провели и списали (в прошлом), а отменяют только сейчас
        # — отмена задним числом.
        SubscriptionService.consume(self.child.id, self.lesson.id, self.direction.id)
        subscription.refresh_from_db()
        self.assertEqual(subscription.sessions_remaining_cache, 7)

        client = _authenticated_client(self.owner)
        response = client.post(
            f"/api/v1/schedule/{self.lesson.id}/cancel/",
            {"reason_category": "room_incident"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        subscription.refresh_from_db()
        self.assertEqual(subscription.sessions_remaining_cache, 8)
        consumption = LessonConsumption.objects.get(child=self.child, lesson_id=self.lesson.id)
        self.assertIsNotNone(consumption.reverted_at)

    def test_cancel_without_prior_consumption_does_not_error(self):
        # Обычный случай — занятие в будущем, посещаемость ещё не отмечена,
        # списания не было. revert() должен молча ничего не делать.
        client = _authenticated_client(self.owner)

        response = client.post(
            f"/api/v1/schedule/{self.lesson.id}/cancel/",
            {"reason_category": "holiday"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertFalse(LessonConsumption.objects.filter(lesson_id=self.lesson.id).exists())


class BulkCancelTest(APITestCase):
    """Массовая отмена за период (TRU-48) — каникулы/праздники."""

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
            phone="+77060000003",
            full_name="Айгуль",
            password="pass12345",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        self.owner = User.objects.create_user(
            phone="+77060000004",
            full_name="Владелец",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )
        tz = timezone.zoneinfo.ZoneInfo("Asia/Almaty")
        base = datetime.datetime(2026, 12, 30, 18, 0, tzinfo=tz)
        self.in_range_room1 = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            room=self.room,
            starts_at=base,
            ends_at=base + datetime.timedelta(hours=1),
        )
        self.in_range_room2 = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            room=self.other_room,
            starts_at=base + datetime.timedelta(days=1),
            ends_at=base + datetime.timedelta(days=1, hours=1),
        )
        self.out_of_range = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            room=self.room,
            starts_at=base + datetime.timedelta(days=10),
            ends_at=base + datetime.timedelta(days=10, hours=1),
        )
        already_cancelled_start = base + datetime.timedelta(hours=3)
        self.already_cancelled = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            room=self.room,
            starts_at=already_cancelled_start,
            ends_at=already_cancelled_start + datetime.timedelta(hours=1),
            status=Lesson.Status.CANCELLED,
        )

    def test_bulk_cancel_requires_date_range(self):
        client = _authenticated_client(self.owner)

        response = client.post(
            "/api/v1/schedule/bulk_cancel/", {"reason_category": "holiday"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bulk_cancel_requires_reason(self):
        client = _authenticated_client(self.owner)

        response = client.post(
            "/api/v1/schedule/bulk_cancel/",
            {"date_from": "2026-12-30", "date_to": "2027-01-05"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bulk_cancel_cancels_only_scheduled_lessons_in_range(self):
        client = _authenticated_client(self.owner)

        response = client.post(
            "/api/v1/schedule/bulk_cancel/",
            {"date_from": "2026-12-30", "date_to": "2027-01-05", "reason_category": "holiday"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["cancelled_count"], 2)
        cancelled_ids = set(response.data["lesson_ids"])
        self.assertEqual(cancelled_ids, {str(self.in_range_room1.id), str(self.in_range_room2.id)})

        self.in_range_room1.refresh_from_db()
        self.in_range_room2.refresh_from_db()
        self.out_of_range.refresh_from_db()
        self.assertEqual(self.in_range_room1.status, Lesson.Status.CANCELLED)
        self.assertEqual(self.in_range_room1.cancel_reason_category, "holiday")
        self.assertEqual(self.in_range_room2.status, Lesson.Status.CANCELLED)
        self.assertEqual(self.out_of_range.status, Lesson.Status.SCHEDULED)

    def test_bulk_cancel_respects_room_filter(self):
        client = _authenticated_client(self.owner)

        response = client.post(
            "/api/v1/schedule/bulk_cancel/",
            {
                "date_from": "2026-12-30",
                "date_to": "2027-01-05",
                "reason_category": "room_incident",
                "room": str(self.room.id),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["cancelled_count"], 1)
        self.in_range_room1.refresh_from_db()
        self.in_range_room2.refresh_from_db()
        self.assertEqual(self.in_range_room1.status, Lesson.Status.CANCELLED)
        self.assertEqual(self.in_range_room2.status, Lesson.Status.SCHEDULED)

    def test_bulk_cancel_forbidden_for_teacher(self):
        client = _authenticated_client(self.teacher)

        response = client.post(
            "/api/v1/schedule/bulk_cancel/",
            {"date_from": "2026-12-30", "date_to": "2027-01-05", "reason_category": "holiday"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.in_range_room1.refresh_from_db()
        self.assertEqual(self.in_range_room1.status, Lesson.Status.SCHEDULED)
