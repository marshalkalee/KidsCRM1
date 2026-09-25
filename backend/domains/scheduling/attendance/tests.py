import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from domains.money.subscriptions.models import Subscription, SubscriptionLedgerEntry
from domains.money.subscriptions.subscription_service import ConsumeOutcome
from domains.money.subscriptions.subscription_types import create_type
from domains.money.subscriptions.subscriptions import add_ledger_entry
from domains.people.clients.models import Child
from domains.platform.core.audit import AuditLog
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.schedule.models import Lesson

from .models import Attendance

User = get_user_model()


def _authenticated_client(user):
    # См. domains.scheduling.schedule.tests._authenticated_client — та же
    # причина: TenantModelViewSet берёт организацию из claim'а JWT
    # (request.organization), обычный force_authenticate() его не создаёт.
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    refresh["organization_id"] = str(user.organization_id)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


class AttendanceFixtureMixin:
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
        self.owner = User.objects.create_user(
            phone="+77010000001",
            full_name="Владелец",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.child = Child.objects.create(
            organization=self.org,
            full_name="Иванов Алихан",
            birth_date=datetime.date.today() - datetime.timedelta(days=365 * 7),
            gender=Child.Gender.MALE,
        )
        GroupMembership.objects.create(
            organization=self.org,
            group=self.group,
            child=self.child,
            joined_at=datetime.date.today(),
        )
        tz = timezone.zoneinfo.ZoneInfo("Asia/Almaty")
        self.lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            starts_at=datetime.datetime(2026, 9, 21, 12, 0, tzinfo=tz),
            ends_at=datetime.datetime(2026, 9, 21, 13, 0, tzinfo=tz),
        )

    def _create_subscription(self, sessions=8):
        st = create_type(
            self.org,
            name=f"{sessions} занятий",
            price=25000,
            quota_sessions=sessions,
            duration_days=60,
            directions=[self.direction],
        )
        sub = Subscription.objects.create(
            organization=self.org,
            child=self.child,
            subscription_type_version=st.versions.latest(),
            direction=self.direction,
            starts_on=datetime.date.today(),
            ends_on=datetime.date.today() + datetime.timedelta(days=60),
            list_price=25000,
            price=25000,
        )
        add_ledger_entry(sub, kind=SubscriptionLedgerEntry.Kind.INITIAL_GRANT, delta=sessions)
        return sub


class AttendanceMarkModelTest(AttendanceFixtureMixin, TestCase):
    def test_mark_present_consumes_one_session(self):
        sub = self._create_subscription(sessions=8)
        attendance = Attendance.objects.create(
            organization=self.org,
            lesson=self.lesson,
            child=self.child,
            status=Attendance.Status.ABSENT,
        )

        attendance.mark(Attendance.Status.PRESENT, actor=self.owner)

        sub.refresh_from_db()
        self.assertEqual(sub.sessions_remaining_cache, 7)
        self.assertTrue(attendance.consumed_from_subscription)
        self.assertEqual(attendance.subscription_id, sub.id)
        self.assertEqual(attendance.consume_outcome, ConsumeOutcome.CONSUMED.value)

    def test_toggle_present_absent_present_charges_exactly_once(self):
        """ТЗ TRU-50: критерий приёмки — переключение статуса туда-обратно
        не плодит списаний."""
        sub = self._create_subscription(sessions=8)
        attendance = Attendance.objects.create(
            organization=self.org,
            lesson=self.lesson,
            child=self.child,
            status=Attendance.Status.ABSENT,
        )

        attendance.mark(Attendance.Status.PRESENT, actor=self.owner)
        attendance.mark(Attendance.Status.ABSENT, actor=self.owner)
        attendance.mark(Attendance.Status.PRESENT, actor=self.owner)

        sub.refresh_from_db()
        self.assertEqual(sub.sessions_remaining_cache, 7)
        self.assertTrue(attendance.consumed_from_subscription)

    def test_mark_absent_reverts_previous_consumption(self):
        sub = self._create_subscription(sessions=8)
        attendance = Attendance.objects.create(
            organization=self.org,
            lesson=self.lesson,
            child=self.child,
            status=Attendance.Status.ABSENT,
        )
        attendance.mark(Attendance.Status.PRESENT, actor=self.owner)

        attendance.mark(
            Attendance.Status.ABSENT,
            actor=self.owner,
            absence_reason=Attendance.AbsenceReason.ILLNESS,
        )

        sub.refresh_from_db()
        self.assertEqual(sub.sessions_remaining_cache, 8)
        self.assertFalse(attendance.consumed_from_subscription)
        self.assertIsNone(attendance.subscription_id)
        self.assertEqual(attendance.absence_reason, Attendance.AbsenceReason.ILLNESS)

    def test_mark_makeup_does_not_consume(self):
        self._create_subscription(sessions=8)
        attendance = Attendance.objects.create(
            organization=self.org,
            lesson=self.lesson,
            child=self.child,
            status=Attendance.Status.ABSENT,
        )

        attendance.mark(Attendance.Status.MAKEUP, actor=self.owner)

        self.assertFalse(attendance.consumed_from_subscription)
        self.assertEqual(attendance.absence_reason, "")

    def test_no_active_subscription_sets_flag_and_calls_admin_task_stub(self):
        attendance = Attendance.objects.create(
            organization=self.org,
            lesson=self.lesson,
            child=self.child,
            status=Attendance.Status.ABSENT,
        )

        with patch(
            "domains.platform.tasks.services.create_admin_task_for_missing_subscription"
        ) as mocked_task:
            attendance.mark(Attendance.Status.PRESENT, actor=self.owner)

        self.assertFalse(attendance.consumed_from_subscription)
        self.assertTrue(attendance.no_subscription_flag)
        self.assertEqual(attendance.consume_outcome, ConsumeOutcome.NO_ACTIVE_SUBSCRIPTION.value)
        mocked_task.assert_called_once_with(attendance=attendance)

    def test_mark_writes_audit_log(self):
        self._create_subscription(sessions=8)
        attendance = Attendance.objects.create(
            organization=self.org,
            lesson=self.lesson,
            child=self.child,
            status=Attendance.Status.ABSENT,
        )

        attendance.mark(Attendance.Status.PRESENT, actor=self.owner)

        log = AuditLog.objects.filter(action=AuditLog.Action.MARK_ATTENDANCE).latest("created_at")
        self.assertEqual(log.actor, self.owner)
        self.assertEqual(log.entity, attendance)


class AttendanceReconciliationTest(AttendanceFixtureMixin, TestCase):
    """Критерий приёмки MVP №3 (ТЗ п. 11.3): остаток, посчитанный из
    журнала посещений, совпадает с показываемым — сверка за две недели
    тестовых данных."""

    def test_balance_matches_ledger_sum_over_two_weeks(self):
        sub = self._create_subscription(sessions=20)
        tz = timezone.zoneinfo.ZoneInfo("Asia/Almaty")
        present_count = 0
        for day in range(14):
            lesson = Lesson.objects.create(
                organization=self.org,
                group=self.group,
                starts_at=datetime.datetime(2026, 9, 21, 12, 0, tzinfo=tz)
                + datetime.timedelta(days=day),
                ends_at=datetime.datetime(2026, 9, 21, 13, 0, tzinfo=tz)
                + datetime.timedelta(days=day),
            )
            attendance = Attendance.objects.create(
                organization=self.org,
                lesson=lesson,
                child=self.child,
                status=Attendance.Status.ABSENT,
            )
            # Через день отмечаем «был», через день — «не был» (болел).
            if day % 2 == 0:
                attendance.mark(Attendance.Status.PRESENT, actor=self.owner)
                present_count += 1
            else:
                attendance.mark(
                    Attendance.Status.ABSENT,
                    actor=self.owner,
                    absence_reason=Attendance.AbsenceReason.ILLNESS,
                )

        sub.refresh_from_db()
        ledger_sum = sub.ledger_entries.aggregate(total=Sum("delta"))["total"]
        self.assertEqual(sub.sessions_remaining_cache, ledger_sum)
        self.assertEqual(sub.sessions_remaining_cache, 20 - present_count)


class AttendanceMarkApiTest(APITestCase):
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
        self.owner = User.objects.create_user(
            phone="+77010000002",
            full_name="Владелец",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.child = Child.objects.create(
            organization=self.org,
            full_name="Петрова Айгерим",
            birth_date=datetime.date.today() - datetime.timedelta(days=365 * 6),
            gender=Child.Gender.FEMALE,
        )
        self.other_child = Child.objects.create(
            organization=self.org,
            full_name="Не в группе",
            birth_date=datetime.date.today() - datetime.timedelta(days=365 * 6),
            gender=Child.Gender.FEMALE,
        )
        GroupMembership.objects.create(
            organization=self.org,
            group=self.group,
            child=self.child,
            joined_at=datetime.date.today(),
        )
        tz = timezone.zoneinfo.ZoneInfo("Asia/Almaty")
        self.lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            starts_at=datetime.datetime(2026, 9, 21, 12, 0, tzinfo=tz),
            ends_at=datetime.datetime(2026, 9, 21, 13, 0, tzinfo=tz),
        )
        st = create_type(
            self.org,
            name="8 занятий",
            price=25000,
            quota_sessions=8,
            duration_days=60,
            directions=[self.direction],
        )
        self.sub = Subscription.objects.create(
            organization=self.org,
            child=self.child,
            subscription_type_version=st.versions.latest(),
            direction=self.direction,
            starts_on=datetime.date.today(),
            ends_on=datetime.date.today() + datetime.timedelta(days=60),
            list_price=25000,
            price=25000,
        )
        add_ledger_entry(self.sub, kind=SubscriptionLedgerEntry.Kind.INITIAL_GRANT, delta=8)

    def test_mark_present_via_api_creates_attendance_and_consumes(self):
        client = _authenticated_client(self.owner)

        response = client.post(
            "/api/v1/attendance/mark/",
            {"lesson": str(self.lesson.id), "child": str(self.child.id), "status": "present"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["consumed_from_subscription"])
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.sessions_remaining_cache, 7)
        self.assertEqual(Attendance.objects.filter(lesson=self.lesson, child=self.child).count(), 1)

    def test_mark_is_idempotent_across_repeated_calls(self):
        client = _authenticated_client(self.owner)
        payload = {"lesson": str(self.lesson.id), "child": str(self.child.id), "status": "present"}

        for _ in range(3):
            response = client.post("/api/v1/attendance/mark/", payload)
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(Attendance.objects.filter(lesson=self.lesson, child=self.child).count(), 1)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.sessions_remaining_cache, 7)

    def test_mark_rejects_child_not_enrolled_in_lesson(self):
        client = _authenticated_client(self.owner)

        response = client.post(
            "/api/v1/attendance/mark/",
            {"lesson": str(self.lesson.id), "child": str(self.other_child.id), "status": "present"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("child", response.data)

    def test_mark_requires_authentication(self):
        response = self.client.post(
            "/api/v1/attendance/mark/",
            {"lesson": str(self.lesson.id), "child": str(self.child.id), "status": "present"},
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_filters_by_lesson(self):
        client = _authenticated_client(self.owner)
        client.post(
            "/api/v1/attendance/mark/",
            {"lesson": str(self.lesson.id), "child": str(self.child.id), "status": "present"},
        )

        response = client.get("/api/v1/attendance/", {"lesson": str(self.lesson.id)})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["child"], self.child.id)


class AttendanceRosterAndBulkApiTest(APITestCase):
    """TRU-56: список детей занятия для экрана отметки + «отметить всех
    пришедшими» + RBAC (преподаватель — только свои занятия)."""

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
        self.owner = User.objects.create_user(
            phone="+77010000003",
            full_name="Владелец",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.teacher = User.objects.create_user(
            phone="+77010000004",
            full_name="Своя преподавательница",
            password="pass12345",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        self.other_teacher = User.objects.create_user(
            phone="+77010000005",
            full_name="Чужой преподаватель",
            password="pass12345",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        self.children = [
            Child.objects.create(
                organization=self.org,
                full_name=f"Ребёнок {i}",
                birth_date=datetime.date.today() - datetime.timedelta(days=365 * 7),
                gender=Child.Gender.FEMALE,
            )
            for i in range(3)
        ]
        for child in self.children:
            GroupMembership.objects.create(
                organization=self.org,
                group=self.group,
                child=child,
                joined_at=datetime.date.today(),
            )
        tz = timezone.zoneinfo.ZoneInfo("Asia/Almaty")
        self.lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            teacher=self.teacher,
            starts_at=datetime.datetime(2026, 9, 21, 12, 0, tzinfo=tz),
            ends_at=datetime.datetime(2026, 9, 21, 13, 0, tzinfo=tz),
        )
        st = create_type(
            self.org,
            name="8 занятий",
            price=25000,
            quota_sessions=8,
            duration_days=60,
            directions=[self.direction],
        )
        self.sub = Subscription.objects.create(
            organization=self.org,
            child=self.children[0],
            subscription_type_version=st.versions.latest(),
            direction=self.direction,
            starts_on=datetime.date.today(),
            ends_on=datetime.date.today() + datetime.timedelta(days=60),
            list_price=25000,
            price=25000,
        )
        add_ledger_entry(self.sub, kind=SubscriptionLedgerEntry.Kind.INITIAL_GRANT, delta=8)
        # children[1] и children[2] — намеренно без абонемента.

    def test_roster_lists_all_participants_unmarked_by_default(self):
        client = _authenticated_client(self.owner)

        response = client.get("/api/v1/attendance/roster/", {"lesson": str(self.lesson.id)})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["participants_count"], 3)
        self.assertEqual(response.data["marked_count"], 0)
        statuses = {row["status"] for row in response.data["results"]}
        self.assertEqual(statuses, {None})

    def test_roster_reflects_already_marked_attendance_on_reopen(self):
        client = _authenticated_client(self.owner)
        client.post(
            "/api/v1/attendance/mark/",
            {"lesson": str(self.lesson.id), "child": str(self.children[0].id), "status": "present"},
        )

        response = client.get("/api/v1/attendance/roster/", {"lesson": str(self.lesson.id)})

        child0_id = str(self.children[0].id)
        child1_id = str(self.children[1].id)
        row = next(r for r in response.data["results"] if r["child"] == child0_id)
        self.assertEqual(row["status"], "present")
        self.assertTrue(row["consumed_from_subscription"])
        other_row = next(r for r in response.data["results"] if r["child"] == child1_id)
        self.assertIsNone(other_row["status"])

    def test_roster_flags_missing_subscription(self):
        client = _authenticated_client(self.owner)
        client.post(
            "/api/v1/attendance/mark/",
            {"lesson": str(self.lesson.id), "child": str(self.children[1].id), "status": "present"},
        )

        response = client.get("/api/v1/attendance/roster/", {"lesson": str(self.lesson.id)})

        child1_id = str(self.children[1].id)
        row = next(r for r in response.data["results"] if r["child"] == child1_id)
        self.assertFalse(row["consumed_from_subscription"])
        self.assertTrue(row["no_subscription_flag"])

    def test_mark_all_present_marks_only_unmarked_children(self):
        client = _authenticated_client(self.owner)
        # children[2] уже отмечен «не был» — bulk не должен это перезаписывать.
        client.post(
            "/api/v1/attendance/mark/",
            {"lesson": str(self.lesson.id), "child": str(self.children[2].id), "status": "absent"},
        )

        response = client.post(
            "/api/v1/attendance/mark-all-present/", {"lesson": str(self.lesson.id)}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["marked_count"], 2)
        self.children[2].refresh_from_db()
        untouched = Attendance.objects.get(lesson=self.lesson, child=self.children[2])
        self.assertEqual(untouched.status, Attendance.Status.ABSENT)
        marked_present = Attendance.objects.filter(
            lesson=self.lesson, status=Attendance.Status.PRESENT
        ).count()
        self.assertEqual(marked_present, 2)

    def test_mark_all_present_is_idempotent(self):
        client = _authenticated_client(self.owner)
        client.post("/api/v1/attendance/mark-all-present/", {"lesson": str(self.lesson.id)})

        response = client.post(
            "/api/v1/attendance/mark-all-present/", {"lesson": str(self.lesson.id)}
        )

        self.assertEqual(response.data["marked_count"], 0)
        self.assertEqual(Attendance.objects.filter(lesson=self.lesson).count(), 3)

    def test_teacher_can_access_own_lesson(self):
        client = _authenticated_client(self.teacher)

        response = client.get("/api/v1/attendance/roster/", {"lesson": str(self.lesson.id)})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_teacher_cannot_access_foreign_lesson_roster(self):
        client = _authenticated_client(self.other_teacher)

        response = client.get("/api/v1/attendance/roster/", {"lesson": str(self.lesson.id)})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_teacher_cannot_mark_foreign_lesson(self):
        client = _authenticated_client(self.other_teacher)

        response = client.post(
            "/api/v1/attendance/mark/",
            {"lesson": str(self.lesson.id), "child": str(self.children[0].id), "status": "present"},
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_teacher_cannot_bulk_mark_foreign_lesson(self):
        client = _authenticated_client(self.other_teacher)

        response = client.post(
            "/api/v1/attendance/mark-all-present/", {"lesson": str(self.lesson.id)}
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class AttendanceRetroactiveEditTest(AttendanceFixtureMixin, TestCase):
    """TRU-52: правка отметки за занятие, которое уже прошло, должна быть
    видна отдельно от обычной первой отметки. self.lesson (из фикстуры) —
    2026-09-21, в прошлом относительно текущей даты теста."""

    def test_first_mark_is_not_retroactive(self):
        attendance = Attendance.objects.create(
            organization=self.org,
            lesson=self.lesson,
            child=self.child,
            status=Attendance.Status.ABSENT,
        )

        attendance.mark(Attendance.Status.PRESENT, actor=self.owner)

        self.assertFalse(attendance.is_retroactive_edit)

    def test_editing_past_lesson_flags_retroactive(self):
        attendance = Attendance.objects.create(
            organization=self.org,
            lesson=self.lesson,
            child=self.child,
            status=Attendance.Status.ABSENT,
        )
        attendance.mark(Attendance.Status.PRESENT, actor=self.owner)

        attendance.mark(
            Attendance.Status.ABSENT,
            actor=self.owner,
            absence_reason=Attendance.AbsenceReason.ILLNESS,
        )

        self.assertTrue(attendance.is_retroactive_edit)

    def test_resubmitting_same_status_does_not_flag_retroactive(self):
        attendance = Attendance.objects.create(
            organization=self.org,
            lesson=self.lesson,
            child=self.child,
            status=Attendance.Status.ABSENT,
        )
        attendance.mark(Attendance.Status.PRESENT, actor=self.owner)

        attendance.mark(Attendance.Status.PRESENT, actor=self.owner)

        self.assertFalse(attendance.is_retroactive_edit)

    def test_editing_same_day_lesson_is_not_retroactive(self):
        tz = timezone.zoneinfo.ZoneInfo("Asia/Almaty")
        now = timezone.now().astimezone(tz)
        todays_lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            starts_at=now.replace(hour=8, minute=0, second=0, microsecond=0),
            ends_at=now.replace(hour=9, minute=0, second=0, microsecond=0),
        )
        attendance = Attendance.objects.create(
            organization=self.org,
            lesson=todays_lesson,
            child=self.child,
            status=Attendance.Status.ABSENT,
        )
        attendance.mark(Attendance.Status.PRESENT, actor=self.owner)

        attendance.mark(Attendance.Status.ABSENT, actor=self.owner)

        self.assertFalse(attendance.is_retroactive_edit)

    def test_retroactive_flag_is_sticky(self):
        """Один раз выставленный флаг не снимается последующими правками —
        это исторический факт про запись, не текущее состояние."""
        attendance = Attendance.objects.create(
            organization=self.org,
            lesson=self.lesson,
            child=self.child,
            status=Attendance.Status.ABSENT,
        )
        attendance.mark(Attendance.Status.PRESENT, actor=self.owner)
        attendance.mark(Attendance.Status.ABSENT, actor=self.owner)
        self.assertTrue(attendance.is_retroactive_edit)

        attendance.mark(Attendance.Status.MAKEUP, actor=self.owner)

        self.assertTrue(attendance.is_retroactive_edit)

    def test_retroactive_edit_recalculates_consumption(self):
        """Критерий приёмки: откат «пришёл» возвращает занятие на
        абонемент — в т.ч. когда это правка задним числом."""
        sub = self._create_subscription(sessions=8)
        attendance = Attendance.objects.create(
            organization=self.org,
            lesson=self.lesson,
            child=self.child,
            status=Attendance.Status.ABSENT,
        )
        attendance.mark(Attendance.Status.PRESENT, actor=self.owner)
        sub.refresh_from_db()
        self.assertEqual(sub.sessions_remaining_cache, 7)

        # Родитель оспорил отметку через несколько дней — администратор
        # правит на «не был».
        attendance.mark(
            Attendance.Status.ABSENT,
            actor=self.owner,
            absence_reason=Attendance.AbsenceReason.FAMILY,
        )

        self.assertTrue(attendance.is_retroactive_edit)
        sub.refresh_from_db()
        self.assertEqual(sub.sessions_remaining_cache, 8)

    def test_audit_log_records_old_and_new_values_on_retroactive_edit(self):
        attendance = Attendance.objects.create(
            organization=self.org,
            lesson=self.lesson,
            child=self.child,
            status=Attendance.Status.ABSENT,
        )
        attendance.mark(Attendance.Status.PRESENT, actor=self.owner)

        attendance.mark(
            Attendance.Status.ABSENT,
            actor=self.owner,
            absence_reason=Attendance.AbsenceReason.ILLNESS,
        )

        log = AuditLog.objects.filter(action=AuditLog.Action.MARK_ATTENDANCE).latest("created_at")
        self.assertEqual(log.before["status"], Attendance.Status.PRESENT)
        self.assertEqual(log.after["status"], Attendance.Status.ABSENT)
        self.assertTrue(log.after["is_retroactive_edit"])


class AttendanceUnmarkedYesterdayApiTest(APITestCase):
    """TRU-52, ТЗ п. 4.5: выборка вчерашних занятий без полной отметки —
    для центра уведомлений (TRU-72)."""

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
        self.owner = User.objects.create_user(
            phone="+77010000006",
            full_name="Владелец",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.teacher = User.objects.create_user(
            phone="+77010000007",
            full_name="Преподавательница",
            password="pass12345",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        self.other_teacher = User.objects.create_user(
            phone="+77010000008",
            full_name="Другой преподаватель",
            password="pass12345",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        self.child = Child.objects.create(
            organization=self.org,
            full_name="Ребёнок",
            birth_date=datetime.date.today() - datetime.timedelta(days=365 * 7),
            gender=Child.Gender.FEMALE,
        )
        GroupMembership.objects.create(
            organization=self.org,
            group=self.group,
            child=self.child,
            joined_at=datetime.date.today(),
        )

        tz = timezone.zoneinfo.ZoneInfo("Asia/Almaty")
        yesterday_noon = (timezone.now().astimezone(tz) - datetime.timedelta(days=1)).replace(
            hour=12, minute=0, second=0, microsecond=0
        )
        self.unmarked_lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            teacher=self.teacher,
            starts_at=yesterday_noon,
            ends_at=yesterday_noon + datetime.timedelta(hours=1),
        )
        self.fully_marked_lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            teacher=self.teacher,
            starts_at=yesterday_noon + datetime.timedelta(hours=2),
            ends_at=yesterday_noon + datetime.timedelta(hours=3),
        )
        Attendance.objects.create(
            organization=self.org,
            lesson=self.fully_marked_lesson,
            child=self.child,
            status=Attendance.Status.ABSENT,
        ).mark(Attendance.Status.PRESENT, actor=self.owner)

        today_noon = (
            timezone.now().astimezone(tz).replace(hour=12, minute=0, second=0, microsecond=0)
        )
        self.todays_lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            teacher=self.teacher,
            starts_at=today_noon,
            ends_at=today_noon + datetime.timedelta(hours=1),
        )

    def test_lists_unmarked_yesterday_lesson(self):
        client = _authenticated_client(self.owner)

        response = client.get("/api/v1/attendance/unmarked-yesterday/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        lesson_ids = {r["lesson"] for r in response.data["results"]}
        self.assertIn(str(self.unmarked_lesson.id), lesson_ids)

    def test_excludes_fully_marked_lesson(self):
        client = _authenticated_client(self.owner)

        response = client.get("/api/v1/attendance/unmarked-yesterday/")

        lesson_ids = {r["lesson"] for r in response.data["results"]}
        self.assertNotIn(str(self.fully_marked_lesson.id), lesson_ids)

    def test_excludes_todays_lesson(self):
        client = _authenticated_client(self.owner)

        response = client.get("/api/v1/attendance/unmarked-yesterday/")

        lesson_ids = {r["lesson"] for r in response.data["results"]}
        self.assertNotIn(str(self.todays_lesson.id), lesson_ids)

    def test_teacher_sees_only_own_unmarked_lessons(self):
        client = _authenticated_client(self.other_teacher)

        response = client.get("/api/v1/attendance/unmarked-yesterday/")

        self.assertEqual(response.data["results"], [])
