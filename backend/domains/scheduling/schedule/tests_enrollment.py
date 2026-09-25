import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from domains.money.subscriptions.models import Subscription, SubscriptionLedgerEntry
from domains.money.subscriptions.subscription_types import create_type
from domains.money.subscriptions.subscriptions import add_ledger_entry
from domains.people.clients.models import Child
from domains.platform.core.audit import AuditLog
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.scheduling.attendance.models import Attendance
from domains.scheduling.groups.models import Group, GroupMembership

from .enrollment_service import EnrollOutcome, LessonService
from .models import Lesson, LessonEnrollment

User = get_user_model()


def _authenticated_client(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    refresh["organization_id"] = str(user.organization_id)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


class EnrollmentFixtureMixin:
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.branch = Branch.objects.create(organization=self.org, name="Главный")
        self.direction = Direction.objects.create(organization=self.org, name="Балет")
        self.group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Балет — Младшая",
            capacity=2,
        )
        self.owner = User.objects.create_user(
            phone="+77020000001",
            full_name="Владелец",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.teacher = User.objects.create_user(
            phone="+77020000002",
            full_name="Преподавательница",
            password="pass12345",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        self.member = Child.objects.create(
            organization=self.org,
            full_name="Постоянный участник",
            birth_date=datetime.date.today() - datetime.timedelta(days=365 * 7),
            gender=Child.Gender.FEMALE,
        )
        GroupMembership.objects.create(
            organization=self.org,
            group=self.group,
            child=self.member,
            joined_at=datetime.date.today(),
        )
        self.outsider = Child.objects.create(
            organization=self.org,
            full_name="Ребёнок из другой группы",
            birth_date=datetime.date.today() - datetime.timedelta(days=365 * 7),
            gender=Child.Gender.MALE,
        )
        tz = timezone.zoneinfo.ZoneInfo("Asia/Almaty")
        future = timezone.now().astimezone(tz) + datetime.timedelta(days=1)
        self.lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            teacher=self.teacher,
            starts_at=future,
            ends_at=future + datetime.timedelta(hours=1),
        )


class LessonServiceEnrollTest(EnrollmentFixtureMixin, TestCase):
    def test_enroll_makeup_success(self):
        result = LessonService.enroll(
            self.lesson.id, self.outsider.id, LessonEnrollment.Kind.MAKEUP, actor=self.owner
        )

        self.assertEqual(result.outcome, EnrollOutcome.ENROLLED)
        enrollment = LessonEnrollment.objects.get(id=result.enrollment_id)
        self.assertEqual(enrollment.kind, LessonEnrollment.Kind.MAKEUP)
        self.assertIsNone(enrollment.cancelled_at)

    def test_enrolled_child_appears_in_participants(self):
        LessonService.enroll(
            self.lesson.id, self.outsider.id, LessonEnrollment.Kind.TRIAL, actor=self.owner
        )

        participant_ids = set(self.lesson.participants().values_list("id", flat=True))

        self.assertIn(self.outsider.id, participant_ids)
        self.assertIn(self.member.id, participant_ids)

    def test_cannot_enroll_existing_group_member(self):
        result = LessonService.enroll(
            self.lesson.id, self.member.id, LessonEnrollment.Kind.MAKEUP, actor=self.owner
        )

        self.assertEqual(result.outcome, EnrollOutcome.ALREADY_ENROLLED)

    def test_cannot_enroll_same_child_twice(self):
        LessonService.enroll(
            self.lesson.id, self.outsider.id, LessonEnrollment.Kind.MAKEUP, actor=self.owner
        )

        result = LessonService.enroll(
            self.lesson.id, self.outsider.id, LessonEnrollment.Kind.TRIAL, actor=self.owner
        )

        self.assertEqual(result.outcome, EnrollOutcome.ALREADY_ENROLLED)

    def test_capacity_exceeded_without_confirm_blocks(self):
        # capacity=2, уже 1 постоянный участник — второй ребёнок "поверх"
        # заполнит группу ровно по вместимости (не исключение), третий —
        # превышение.
        second_outsider = Child.objects.create(
            organization=self.org,
            full_name="Второй лишний",
            birth_date=datetime.date.today() - datetime.timedelta(days=365 * 7),
            gender=Child.Gender.FEMALE,
        )
        LessonService.enroll(
            self.lesson.id, self.outsider.id, LessonEnrollment.Kind.MAKEUP, actor=self.owner
        )

        result = LessonService.enroll(
            self.lesson.id, second_outsider.id, LessonEnrollment.Kind.MAKEUP, actor=self.owner
        )

        self.assertEqual(result.outcome, EnrollOutcome.CAPACITY_EXCEEDED)
        self.assertEqual(result.capacity, 2)
        self.assertEqual(result.current_count, 2)
        self.assertFalse(
            LessonEnrollment.objects.filter(lesson=self.lesson, child=second_outsider).exists()
        )

    def test_capacity_exceeded_with_confirm_enrolls_anyway(self):
        second_outsider = Child.objects.create(
            organization=self.org,
            full_name="Второй лишний",
            birth_date=datetime.date.today() - datetime.timedelta(days=365 * 7),
            gender=Child.Gender.FEMALE,
        )
        LessonService.enroll(
            self.lesson.id, self.outsider.id, LessonEnrollment.Kind.MAKEUP, actor=self.owner
        )

        result = LessonService.enroll(
            self.lesson.id,
            second_outsider.id,
            LessonEnrollment.Kind.MAKEUP,
            actor=self.owner,
            confirm_capacity=True,
        )

        self.assertEqual(result.outcome, EnrollOutcome.ENROLLED)

    def test_cannot_enroll_into_cancelled_lesson(self):
        self.lesson.cancel(actor=self.owner, category="other", comment="test")

        result = LessonService.enroll(
            self.lesson.id, self.outsider.id, LessonEnrollment.Kind.MAKEUP, actor=self.owner
        )

        self.assertEqual(result.outcome, EnrollOutcome.LESSON_CANCELLED)

    def test_cannot_enroll_into_past_lesson(self):
        tz = timezone.zoneinfo.ZoneInfo("Asia/Almaty")
        past = timezone.now().astimezone(tz) - datetime.timedelta(days=1)
        past_lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group,
            starts_at=past,
            ends_at=past + datetime.timedelta(hours=1),
        )

        result = LessonService.enroll(
            past_lesson.id, self.outsider.id, LessonEnrollment.Kind.MAKEUP, actor=self.owner
        )

        self.assertEqual(result.outcome, EnrollOutcome.LESSON_IN_PAST)

    def test_enroll_writes_audit_log(self):
        result = LessonService.enroll(
            self.lesson.id, self.outsider.id, LessonEnrollment.Kind.MAKEUP, actor=self.owner
        )

        log = AuditLog.objects.filter(action=AuditLog.Action.ENROLL).latest("created_at")
        self.assertEqual(str(log.object_id), str(result.enrollment_id))


class LessonServiceCancelEnrollmentTest(EnrollmentFixtureMixin, TestCase):
    def test_cancel_enrollment(self):
        result = LessonService.enroll(
            self.lesson.id, self.outsider.id, LessonEnrollment.Kind.MAKEUP, actor=self.owner
        )

        cancelled = LessonService.cancel_enrollment(result.enrollment_id, actor=self.owner)

        self.assertTrue(cancelled)
        enrollment = LessonEnrollment.objects.get(id=result.enrollment_id)
        self.assertIsNotNone(enrollment.cancelled_at)

    def test_cancelled_enrollment_removed_from_participants(self):
        result = LessonService.enroll(
            self.lesson.id, self.outsider.id, LessonEnrollment.Kind.MAKEUP, actor=self.owner
        )
        LessonService.cancel_enrollment(result.enrollment_id, actor=self.owner)

        participant_ids = set(self.lesson.participants().values_list("id", flat=True))

        self.assertNotIn(self.outsider.id, participant_ids)

    def test_cancel_is_idempotent(self):
        result = LessonService.enroll(
            self.lesson.id, self.outsider.id, LessonEnrollment.Kind.MAKEUP, actor=self.owner
        )
        LessonService.cancel_enrollment(result.enrollment_id, actor=self.owner)

        second_cancel = LessonService.cancel_enrollment(result.enrollment_id, actor=self.owner)

        self.assertFalse(second_cancel)


class EnrollmentAttendanceChargingTest(EnrollmentFixtureMixin, TestCase):
    """TRU-53: правило списания по типу (M1) — отработка и пробное не
    списывают новый сеанс с абонемента."""

    def _create_subscription(self, child, sessions=8):
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
            child=child,
            subscription_type_version=st.versions.latest(),
            direction=self.direction,
            starts_on=datetime.date.today(),
            ends_on=datetime.date.today() + datetime.timedelta(days=60),
            list_price=25000,
            price=25000,
        )
        add_ledger_entry(sub, kind=SubscriptionLedgerEntry.Kind.INITIAL_GRANT, delta=sessions)
        return sub

    def test_makeup_attendance_does_not_charge(self):
        sub = self._create_subscription(self.outsider)
        LessonService.enroll(
            self.lesson.id, self.outsider.id, LessonEnrollment.Kind.MAKEUP, actor=self.owner
        )
        attendance = Attendance.objects.create(
            organization=self.org,
            lesson=self.lesson,
            child=self.outsider,
            status=Attendance.Status.ABSENT,
        )

        attendance.mark(Attendance.Status.PRESENT, actor=self.owner)

        self.assertFalse(attendance.consumed_from_subscription)
        self.assertEqual(attendance.consume_outcome, "makeup_no_charge")
        self.assertFalse(attendance.no_subscription_flag)
        sub.refresh_from_db()
        self.assertEqual(sub.sessions_remaining_cache, 8)

    def test_trial_attendance_does_not_charge(self):
        LessonService.enroll(
            self.lesson.id, self.outsider.id, LessonEnrollment.Kind.TRIAL, actor=self.owner
        )
        attendance = Attendance.objects.create(
            organization=self.org,
            lesson=self.lesson,
            child=self.outsider,
            status=Attendance.Status.ABSENT,
        )

        attendance.mark(Attendance.Status.PRESENT, actor=self.owner)

        self.assertFalse(attendance.consumed_from_subscription)
        self.assertEqual(attendance.consume_outcome, "trial_no_charge")
        self.assertFalse(attendance.no_subscription_flag)

    def test_regular_member_still_charged_normally(self):
        sub = self._create_subscription(self.member)
        attendance = Attendance.objects.create(
            organization=self.org,
            lesson=self.lesson,
            child=self.member,
            status=Attendance.Status.ABSENT,
        )

        attendance.mark(Attendance.Status.PRESENT, actor=self.owner)

        self.assertTrue(attendance.consumed_from_subscription)
        sub.refresh_from_db()
        self.assertEqual(sub.sessions_remaining_cache, 7)


class LessonEnrollmentApiTest(EnrollmentFixtureMixin, APITestCase):
    def test_owner_can_enroll(self):
        client = _authenticated_client(self.owner)

        response = client.post(
            "/api/v1/schedule/enrollments/",
            {"lesson": str(self.lesson.id), "child": str(self.outsider.id), "kind": "makeup"},
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["kind"], "makeup")
        self.assertEqual(response.data["child"], self.outsider.id)

    def test_teacher_cannot_enroll(self):
        client = _authenticated_client(self.teacher)

        response = client.post(
            "/api/v1/schedule/enrollments/",
            {"lesson": str(self.lesson.id), "child": str(self.outsider.id), "kind": "makeup"},
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_duplicate_enroll_returns_400(self):
        client = _authenticated_client(self.owner)
        client.post(
            "/api/v1/schedule/enrollments/",
            {"lesson": str(self.lesson.id), "child": str(self.outsider.id), "kind": "makeup"},
        )

        response = client.post(
            "/api/v1/schedule/enrollments/",
            {"lesson": str(self.lesson.id), "child": str(self.outsider.id), "kind": "trial"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_capacity_exceeded_returns_409_with_confirm_hint(self):
        client = _authenticated_client(self.owner)
        second_outsider = Child.objects.create(
            organization=self.org,
            full_name="Второй лишний",
            birth_date=datetime.date.today() - datetime.timedelta(days=365 * 7),
            gender=Child.Gender.FEMALE,
        )
        client.post(
            "/api/v1/schedule/enrollments/",
            {"lesson": str(self.lesson.id), "child": str(self.outsider.id), "kind": "makeup"},
        )

        response = client.post(
            "/api/v1/schedule/enrollments/",
            {"lesson": str(self.lesson.id), "child": str(second_outsider.id), "kind": "makeup"},
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("capacity", response.data)

        response = client.post(
            "/api/v1/schedule/enrollments/",
            {
                "lesson": str(self.lesson.id),
                "child": str(second_outsider.id),
                "kind": "makeup",
                "confirm_capacity": True,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_cancel_enrollment_via_api(self):
        client = _authenticated_client(self.owner)
        create_response = client.post(
            "/api/v1/schedule/enrollments/",
            {"lesson": str(self.lesson.id), "child": str(self.outsider.id), "kind": "makeup"},
        )
        enrollment_id = create_response.data["id"]

        response = client.post(f"/api/v1/schedule/enrollments/{enrollment_id}/cancel/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.data["cancelled_at"])

    def test_roster_shows_enrollment_kind(self):
        client = _authenticated_client(self.owner)
        client.post(
            "/api/v1/schedule/enrollments/",
            {"lesson": str(self.lesson.id), "child": str(self.outsider.id), "kind": "trial"},
        )

        response = client.get("/api/v1/attendance/roster/", {"lesson": str(self.lesson.id)})

        outsider_id = str(self.outsider.id)
        member_id = str(self.member.id)
        row = next(r for r in response.data["results"] if r["child"] == outsider_id)
        self.assertEqual(row["enrollment_kind"], "trial")
        member_row = next(r for r in response.data["results"] if r["child"] == member_id)
        self.assertIsNone(member_row["enrollment_kind"])
