import datetime

from django.utils import timezone
from rest_framework.test import APITestCase

from domains.people.clients.models import Child
from domains.platform.tasks.models import Task
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User
from domains.scheduling.attendance.models import Attendance
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.schedule.models import Lesson, LessonEnrollment

from .models import ParentAccount, ParentLessonRequest


class ParentRequestStaffApiTests(APITestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.branch = Branch.objects.create(organization=self.organization, name="Главный")
        self.other_branch = Branch.objects.create(organization=self.organization, name="Другой")
        self.direction = Direction.objects.create(organization=self.organization, name="Балет")
        self.group = Group.objects.create(
            organization=self.organization,
            branch=self.branch,
            direction=self.direction,
            name="Балет 8–10",
            capacity=3,
        )
        self.other_group = Group.objects.create(
            organization=self.organization,
            branch=self.other_branch,
            direction=self.direction,
            name="Балет 11–13",
            capacity=3,
        )
        self.owner = User.objects.create_user(
            phone="+77000000001",
            password="test",
            full_name="Владелец",
            organization=self.organization,
            role=User.Role.OWNER,
        )
        self.admin = User.objects.create_user(
            phone="+77000000002",
            password="test",
            full_name="Администратор",
            organization=self.organization,
            role=User.Role.ADMIN,
        )
        self.admin.branches.add(self.branch)
        self.teacher = User.objects.create_user(
            phone="+77000000003",
            password="test",
            full_name="Преподаватель",
            organization=self.organization,
            role=User.Role.TEACHER,
        )
        self.child = Child.objects.create(
            organization=self.organization,
            full_name="Алина Тестова",
            birth_date=datetime.date(2017, 1, 1),
        )
        self.account = ParentAccount.objects.create(phone="+77001112233")
        self.client.force_authenticate(self.owner)

    def lesson(self, *, group=None, days=2):
        starts_at = timezone.now() + datetime.timedelta(days=days)
        return Lesson.objects.create(
            organization=self.organization,
            group=group or self.group,
            starts_at=starts_at,
            ends_at=starts_at + datetime.timedelta(hours=1),
        )

    def request(self, *, lesson=None, request_type="enroll", kind="regular", **extra):
        return ParentLessonRequest.objects.create(
            organization=self.organization,
            requested_by=self.account,
            child=self.child,
            lesson=lesson or self.lesson(),
            type=request_type,
            kind=kind,
            spots_available_at_request=2 if request_type == "enroll" else None,
            **extra,
        )

    def task_for(self, parent_request):
        return Task.objects.create(
            organization=self.organization,
            type=Task.Type.PARENT_REQUEST,
            source=Task.Source.AUTO,
            source_key=f"parent-request:{parent_request.id}",
            title="Запрос родителя",
        )

    def test_list_is_newest_first_and_scoped_to_admin_branch(self):
        visible = self.request()
        self.request(lesson=self.lesson(group=self.other_group))
        self.client.force_authenticate(self.admin)

        response = self.client.get("/api/v1/parent-requests/")

        self.assertEqual(response.status_code, 200, response.data)
        rows = response.data.get("results", response.data)
        self.assertEqual([str(row["id"]) for row in rows], [str(visible.id)])
        self.assertEqual(rows[0]["lesson"]["branch_name"], self.branch.name)
        self.assertEqual(rows[0]["spots_available_now"], 3)

    def test_teacher_cannot_open_staff_requests(self):
        self.client.force_authenticate(self.teacher)
        self.assertEqual(self.client.get("/api/v1/parent-requests/").status_code, 403)

    def test_approve_regular_enrolls_and_closes_task(self):
        parent_request = self.request()
        task = self.task_for(parent_request)

        response = self.client.post(
            f"/api/v1/parent-requests/{parent_request.id}/approve/", {}, format="json"
        )

        self.assertEqual(response.status_code, 200, response.data)
        parent_request.refresh_from_db()
        task.refresh_from_db()
        enrollment = LessonEnrollment.objects.get(
            lesson=parent_request.lesson, child=self.child, cancelled_at__isnull=True
        )
        self.assertEqual(enrollment.kind, LessonEnrollment.Kind.REGULAR)
        self.assertEqual(parent_request.status, ParentLessonRequest.Status.APPROVED)
        self.assertEqual(parent_request.processed_by, self.owner)
        self.assertEqual(task.status, Task.Status.DONE)

    def test_approve_uses_role_scope_not_global_active_branch(self):
        parent_request = self.request(lesson=self.lesson(group=self.other_group))

        response = self.client.post(
            f"/api/v1/parent-requests/{parent_request.id}/approve/",
            {},
            format="json",
            HTTP_X_BRANCH_ID=str(self.branch.id),
        )

        self.assertEqual(response.status_code, 200, response.data)
        parent_request.refresh_from_db()
        self.assertEqual(parent_request.status, ParentLessonRequest.Status.APPROVED)
        self.assertTrue(
            LessonEnrollment.objects.filter(
                lesson=parent_request.lesson,
                child=self.child,
                cancelled_at__isnull=True,
            ).exists()
        )

    def test_capacity_is_rechecked_when_approving(self):
        parent_request = self.request()
        self.group.capacity = 1
        self.group.save(update_fields=["capacity"])
        another = Child.objects.create(
            organization=self.organization,
            full_name="Уже записан",
            birth_date=datetime.date(2017, 1, 1),
        )
        GroupMembership.objects.create(
            organization=self.organization,
            group=self.group,
            child=another,
            joined_at=timezone.localdate(),
        )

        response = self.client.post(
            f"/api/v1/parent-requests/{parent_request.id}/approve/", {}, format="json"
        )

        self.assertEqual(response.status_code, 409, response.data)
        parent_request.refresh_from_db()
        self.assertEqual(parent_request.status, ParentLessonRequest.Status.NEW)
        self.assertFalse(
            LessonEnrollment.objects.filter(lesson=parent_request.lesson, child=self.child).exists()
        )

    def test_reject_requires_reason_and_parent_can_receive_it(self):
        parent_request = self.request()
        url = f"/api/v1/parent-requests/{parent_request.id}/reject/"
        self.assertEqual(self.client.post(url, {}, format="json").status_code, 400)

        response = self.client.post(url, {"reason": "Группа уже заполнена"}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        parent_request.refresh_from_db()
        self.assertEqual(parent_request.status, ParentLessonRequest.Status.REJECTED)
        self.assertEqual(parent_request.rejection_reason, "Группа уже заполнена")

    def test_approve_cancellation_marks_absence_with_parent_reason(self):
        lesson = self.lesson()
        GroupMembership.objects.create(
            organization=self.organization,
            group=self.group,
            child=self.child,
            joined_at=timezone.localdate(),
        )
        parent_request = self.request(
            lesson=lesson,
            request_type="cancel",
            cancel_reason=ParentLessonRequest.CancelReason.ILLNESS,
            notice_hours_required=24,
            notice_is_timely=True,
            will_be_charged=False,
        )

        response = self.client.post(
            f"/api/v1/parent-requests/{parent_request.id}/approve/", {}, format="json"
        )

        self.assertEqual(response.status_code, 200, response.data)
        attendance = Attendance.objects.get(lesson=lesson, child=self.child)
        self.assertEqual(attendance.status, Attendance.Status.ABSENT)
        self.assertEqual(attendance.absence_reason, Attendance.AbsenceReason.ILLNESS)
        self.assertFalse(attendance.consumed_from_subscription)

    def test_bulk_rejects_same_type_requests(self):
        first = self.request()
        second = self.request(lesson=self.lesson(days=3))

        response = self.client.post(
            "/api/v1/parent-requests/bulk/",
            {
                "ids": [str(first.id), str(second.id)],
                "decision": "reject",
                "reason": "Нет мест на выбранной неделе",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["processed_count"], 2)
        self.assertEqual(
            ParentLessonRequest.objects.filter(status=ParentLessonRequest.Status.REJECTED).count(),
            2,
        )

    def test_past_enrollment_returns_clear_conflict(self):
        parent_request = self.request(lesson=self.lesson(days=-2))

        response = self.client.post(
            f"/api/v1/parent-requests/{parent_request.id}/approve/", {}, format="json"
        )

        self.assertEqual(response.status_code, 409, response.data)
        self.assertIn("прошло", response.data["detail"])
        parent_request.refresh_from_db()
        self.assertEqual(parent_request.status, ParentLessonRequest.Status.NEW)

    def test_notification_contains_new_request_count(self):
        self.request()

        response = self.client.get("/api/v1/notifications/")

        self.assertEqual(response.status_code, 200, response.data)
        item = next(row for row in response.data["items"] if row["kind"] == "parent_requests")
        self.assertEqual((item["count"], item["link"]), (1, "/parent-requests"))
