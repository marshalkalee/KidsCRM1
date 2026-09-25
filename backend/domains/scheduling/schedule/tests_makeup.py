import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from domains.people.clients.models import Child
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.scheduling.attendance.models import Attendance
from domains.scheduling.groups.models import Group, GroupMembership

from .enrollment_service import (
    MAKEUP_EXPIRY_DAYS,
    EnrollOutcome,
    LessonService,
    available_makeups_for_child,
    makeup_candidate_lessons,
)
from .models import Lesson, LessonEnrollment

User = get_user_model()


def _authenticated_client(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    refresh["organization_id"] = str(user.organization_id)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


class MakeupFixtureMixin:
    """Ребёнок пропустил занятие BALLET_A (направление «Балет») N дней
    назад — self.missed_attendance. self.candidate_lesson — будущее
    занятие того же направления с местом. self.other_direction_lesson —
    будущее занятие другого направления (для проверки правила «только то
    же направление»)."""

    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.branch = Branch.objects.create(organization=self.org, name="Главный")
        self.ballet = Direction.objects.create(organization=self.org, name="Балет")
        self.stretching = Direction.objects.create(organization=self.org, name="Растяжка")
        self.owner = User.objects.create_user(
            phone="+77030000001",
            full_name="Владелец",
            password="pass12345",
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.child = Child.objects.create(
            organization=self.org,
            full_name="Пропустивший ребёнок",
            birth_date=datetime.date.today() - datetime.timedelta(days=365 * 7),
            gender=Child.Gender.FEMALE,
        )
        self.group_a = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.ballet,
            name="Балет — А",
            capacity=2,
        )
        GroupMembership.objects.create(
            organization=self.org,
            group=self.group_a,
            child=self.child,
            joined_at=datetime.date.today(),
        )

        self.tz = timezone.zoneinfo.ZoneInfo("Asia/Almaty")
        self.missed_at = timezone.now().astimezone(self.tz) - datetime.timedelta(days=1)
        self.missed_lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group_a,
            starts_at=self.missed_at,
            ends_at=self.missed_at + datetime.timedelta(hours=1),
        )
        self.missed_attendance = Attendance.objects.create(
            organization=self.org,
            lesson=self.missed_lesson,
            child=self.child,
            status=Attendance.Status.ABSENT,
        )

        self.group_b = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.ballet,
            name="Балет — Б",
            capacity=2,
        )
        future = timezone.now().astimezone(self.tz) + datetime.timedelta(days=2)
        self.candidate_lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group_b,
            starts_at=future,
            ends_at=future + datetime.timedelta(hours=1),
        )

        stretching_group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.stretching,
            name="Растяжка — А",
            capacity=2,
        )
        self.other_direction_lesson = Lesson.objects.create(
            organization=self.org,
            group=stretching_group,
            starts_at=future,
            ends_at=future + datetime.timedelta(hours=1),
        )


class LessonServiceMakeupEnrollTest(MakeupFixtureMixin, TestCase):
    def test_enroll_makeup_with_source_attendance(self):
        result = LessonService.enroll(
            self.candidate_lesson.id,
            self.child.id,
            LessonEnrollment.Kind.MAKEUP,
            actor=self.owner,
            source_attendance_id=self.missed_attendance.id,
        )

        self.assertEqual(result.outcome, EnrollOutcome.ENROLLED)
        enrollment = LessonEnrollment.objects.get(id=result.enrollment_id)
        self.assertEqual(enrollment.source_attendance_id, self.missed_attendance.id)

    def test_cannot_makeup_same_absence_twice(self):
        LessonService.enroll(
            self.candidate_lesson.id,
            self.child.id,
            LessonEnrollment.Kind.MAKEUP,
            actor=self.owner,
            source_attendance_id=self.missed_attendance.id,
        )
        second_lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group_b,
            starts_at=self.candidate_lesson.starts_at + datetime.timedelta(days=1),
            ends_at=self.candidate_lesson.ends_at + datetime.timedelta(days=1),
        )

        result = LessonService.enroll(
            second_lesson.id,
            self.child.id,
            LessonEnrollment.Kind.MAKEUP,
            actor=self.owner,
            source_attendance_id=self.missed_attendance.id,
        )

        self.assertEqual(result.outcome, EnrollOutcome.SOURCE_ALREADY_USED)

    def test_cannot_makeup_in_different_direction(self):
        result = LessonService.enroll(
            self.other_direction_lesson.id,
            self.child.id,
            LessonEnrollment.Kind.MAKEUP,
            actor=self.owner,
            source_attendance_id=self.missed_attendance.id,
        )

        self.assertEqual(result.outcome, EnrollOutcome.SOURCE_DIRECTION_MISMATCH)

    def test_cannot_makeup_expired_absence(self):
        expired_at = timezone.now().astimezone(self.tz) - datetime.timedelta(
            days=MAKEUP_EXPIRY_DAYS + 1
        )
        expired_lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group_a,
            starts_at=expired_at,
            ends_at=expired_at + datetime.timedelta(hours=1),
        )
        expired_attendance = Attendance.objects.create(
            organization=self.org,
            lesson=expired_lesson,
            child=self.child,
            status=Attendance.Status.ABSENT,
        )

        result = LessonService.enroll(
            self.candidate_lesson.id,
            self.child.id,
            LessonEnrollment.Kind.MAKEUP,
            actor=self.owner,
            source_attendance_id=expired_attendance.id,
        )

        self.assertEqual(result.outcome, EnrollOutcome.SOURCE_EXPIRED)

    def test_makeup_on_last_valid_day_still_allowed(self):
        boundary_at = timezone.now().astimezone(self.tz) - datetime.timedelta(
            days=MAKEUP_EXPIRY_DAYS
        )
        boundary_lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group_a,
            starts_at=boundary_at,
            ends_at=boundary_at + datetime.timedelta(hours=1),
        )
        boundary_attendance = Attendance.objects.create(
            organization=self.org,
            lesson=boundary_lesson,
            child=self.child,
            status=Attendance.Status.ABSENT,
        )

        result = LessonService.enroll(
            self.candidate_lesson.id,
            self.child.id,
            LessonEnrollment.Kind.MAKEUP,
            actor=self.owner,
            source_attendance_id=boundary_attendance.id,
        )

        self.assertEqual(result.outcome, EnrollOutcome.ENROLLED)

    def test_source_child_mismatch(self):
        other_child = Child.objects.create(
            organization=self.org,
            full_name="Другой ребёнок",
            birth_date=datetime.date.today() - datetime.timedelta(days=365 * 7),
            gender=Child.Gender.MALE,
        )

        result = LessonService.enroll(
            self.candidate_lesson.id,
            other_child.id,
            LessonEnrollment.Kind.MAKEUP,
            actor=self.owner,
            source_attendance_id=self.missed_attendance.id,
        )

        self.assertEqual(result.outcome, EnrollOutcome.SOURCE_CHILD_MISMATCH)

    def test_cancelling_makeup_frees_source_attendance_for_reuse(self):
        result = LessonService.enroll(
            self.candidate_lesson.id,
            self.child.id,
            LessonEnrollment.Kind.MAKEUP,
            actor=self.owner,
            source_attendance_id=self.missed_attendance.id,
        )
        LessonService.cancel_enrollment(result.enrollment_id, actor=self.owner)

        second_lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group_b,
            starts_at=self.candidate_lesson.starts_at + datetime.timedelta(days=1),
            ends_at=self.candidate_lesson.ends_at + datetime.timedelta(days=1),
        )
        retry = LessonService.enroll(
            second_lesson.id,
            self.child.id,
            LessonEnrollment.Kind.MAKEUP,
            actor=self.owner,
            source_attendance_id=self.missed_attendance.id,
        )

        self.assertEqual(retry.outcome, EnrollOutcome.ENROLLED)


class AvailableMakeupsTest(MakeupFixtureMixin, TestCase):
    def test_missed_lesson_appears_available(self):
        rows = available_makeups_for_child(self.org, self.child.id)

        attendance_ids = {row["attendance"].id for row in rows}
        self.assertIn(self.missed_attendance.id, attendance_ids)

    def test_used_absence_not_available(self):
        LessonService.enroll(
            self.candidate_lesson.id,
            self.child.id,
            LessonEnrollment.Kind.MAKEUP,
            actor=self.owner,
            source_attendance_id=self.missed_attendance.id,
        )

        rows = available_makeups_for_child(self.org, self.child.id)

        attendance_ids = {row["attendance"].id for row in rows}
        self.assertNotIn(self.missed_attendance.id, attendance_ids)

    def test_expired_absence_not_available(self):
        expired_at = timezone.now().astimezone(self.tz) - datetime.timedelta(
            days=MAKEUP_EXPIRY_DAYS + 1
        )
        expired_lesson = Lesson.objects.create(
            organization=self.org,
            group=self.group_a,
            starts_at=expired_at,
            ends_at=expired_at + datetime.timedelta(hours=1),
        )
        expired_attendance = Attendance.objects.create(
            organization=self.org,
            lesson=expired_lesson,
            child=self.child,
            status=Attendance.Status.ABSENT,
        )

        rows = available_makeups_for_child(self.org, self.child.id)

        attendance_ids = {row["attendance"].id for row in rows}
        self.assertNotIn(expired_attendance.id, attendance_ids)

    def test_days_left_computed_correctly(self):
        rows = available_makeups_for_child(self.org, self.child.id)

        row = next(r for r in rows if r["attendance"].id == self.missed_attendance.id)
        self.assertEqual(row["days_left"], MAKEUP_EXPIRY_DAYS - 1)


class MakeupCandidateLessonsTest(MakeupFixtureMixin, TestCase):
    def test_same_direction_future_lesson_included(self):
        candidates = makeup_candidate_lessons(self.missed_attendance, self.org)

        self.assertIn(self.candidate_lesson, list(candidates))

    def test_different_direction_lesson_excluded(self):
        candidates = makeup_candidate_lessons(self.missed_attendance, self.org)

        self.assertNotIn(self.other_direction_lesson, list(candidates))

    def test_source_lesson_itself_excluded(self):
        # Пересоздаём пропуск как "будущее" занятие того же направления,
        # чтобы проверить, что кандидат не предлагает отработать занятие
        # отработкой на него же самого.
        candidates = makeup_candidate_lessons(self.missed_attendance, self.org)
        self.assertNotIn(self.missed_lesson, list(candidates))


class MakeupApiTest(MakeupFixtureMixin, APITestCase):
    def test_available_makeups_endpoint(self):
        client = _authenticated_client(self.owner)

        response = client.get(
            "/api/v1/attendance/available-makeups/", {"child": str(self.child.id)}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        attendance_ids = {r["attendance_id"] for r in response.data["results"]}
        self.assertIn(str(self.missed_attendance.id), attendance_ids)

    def test_makeup_candidates_endpoint(self):
        client = _authenticated_client(self.owner)

        response = client.get(f"/api/v1/attendance/{self.missed_attendance.id}/makeup-candidates/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        lesson_ids = {r["id"] for r in response.data["results"]}
        self.assertIn(str(self.candidate_lesson.id), lesson_ids)
        self.assertNotIn(str(self.other_direction_lesson.id), lesson_ids)

    def test_enroll_via_api_with_source_attendance(self):
        client = _authenticated_client(self.owner)

        response = client.post(
            "/api/v1/schedule/enrollments/",
            {
                "lesson": str(self.candidate_lesson.id),
                "child": str(self.child.id),
                "kind": "makeup",
                "source_attendance": str(self.missed_attendance.id),
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["source_attendance"], self.missed_attendance.id)

        # После записи пропуск больше не в списке доступных.
        response = client.get(
            "/api/v1/attendance/available-makeups/", {"child": str(self.child.id)}
        )
        attendance_ids = {r["attendance_id"] for r in response.data["results"]}
        self.assertNotIn(str(self.missed_attendance.id), attendance_ids)
