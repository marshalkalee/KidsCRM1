"""Автоправило «Отметить посещаемость»: неотмеченное прошедшее занятие →
задача преподавателю; ничего не списывается; задача закрывается сама."""

import datetime

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from domains.people.clients.models import Child
from domains.platform.tasks.models import Task
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.tenants.org_settings import RULE_UNMARKED_ATTENDANCE_ENABLED
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.schedule.models import Lesson

from .models import Attendance
from .rules import create_tasks_for_unmarked_lessons


def client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    refresh["organization_id"] = str(user.organization_id)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


class UnmarkedAttendanceRuleTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="QA", slug="qa")
        self.branch = Branch.objects.create(organization=self.org, name="Абая")
        direction = Direction.objects.create(organization=self.org, name="Балет")
        self.group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=direction,
            name="Балет 6–8",
            capacity=10,
        )
        self.teacher = User.objects.create_user(
            phone="+77040000001",
            password="pass12345",
            full_name="Преподаватель",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        self.admin = User.objects.create_user(
            phone="+77040000002",
            password="pass12345",
            full_name="Администратор",
            organization=self.org,
            role=User.Role.ADMIN,
        )
        self.children = []
        for name in ("Ахметова Айя", "Бекова Мира"):
            child = Child.objects.create(
                organization=self.org,
                full_name=name,
                birth_date=datetime.date(2018, 1, 1),
                gender=Child.Gender.FEMALE,
            )
            GroupMembership.objects.create(
                organization=self.org,
                group=self.group,
                child=child,
                joined_at=datetime.date.today() - datetime.timedelta(days=30),
            )
            self.children.append(child)
        self.lesson = self._lesson(days_ago=1)

    def _lesson(self, days_ago, **extra):
        starts = timezone.now() - datetime.timedelta(days=days_ago)
        return Lesson.objects.create(
            organization=self.org,
            group=self.group,
            teacher=extra.pop("teacher", self.teacher),
            starts_at=starts,
            ends_at=starts + datetime.timedelta(hours=1),
            **extra,
        )

    def _tasks(self):
        return Task.objects.filter(type=Task.Type.MARK_ATTENDANCE)

    def test_unmarked_lesson_gets_a_task_for_its_teacher(self):
        Attendance.objects.create(
            organization=self.org, lesson=self.lesson, child=self.children[0], status="present"
        )

        self.assertEqual(create_tasks_for_unmarked_lessons(), 1)

        task = self._tasks().get()
        self.assertEqual(task.assigned_to, self.teacher)
        self.assertEqual(task.source, Task.Source.AUTO)
        self.assertIn("Балет 6–8", task.title)
        self.assertEqual(task.description, "Не отмечены: Бекова Мира")
        self.assertIsNotNone(task.due_at)
        # Повторный запуск не дублирует.
        self.assertEqual(create_tasks_for_unmarked_lessons(), 0)

    def test_nothing_is_charged_or_marked_automatically(self):
        create_tasks_for_unmarked_lessons()
        self.assertFalse(Attendance.objects.exists())

    def test_fully_marked_cancelled_and_todays_lessons_are_skipped(self):
        for child in self.children:
            Attendance.objects.create(
                organization=self.org, lesson=self.lesson, child=child, status="absent"
            )
        self._lesson(days_ago=2, status=Lesson.Status.CANCELLED)
        self._lesson(days_ago=0)  # сегодняшнее — ещё могут отметить

        self.assertEqual(create_tasks_for_unmarked_lessons(), 0)

    def test_lesson_without_teacher_goes_to_branch_admin(self):
        self.lesson.teacher = None
        self.lesson.save(update_fields=["teacher"])

        create_tasks_for_unmarked_lessons()

        self.assertEqual(self._tasks().get().assigned_to, self.admin)

    def test_inactive_or_foreign_teacher_is_replaced_by_branch_admin(self):
        other_org = Organization.objects.create(name="Другой", slug="other")
        foreign = User.objects.create_user(
            phone="+77040000003",
            password="pass12345",
            full_name="Чужой Преподаватель",
            organization=other_org,
            role=User.Role.TEACHER,
        )
        self.lesson.teacher = foreign
        self.lesson.save(update_fields=["teacher"])
        self._lesson(days_ago=2)
        self.teacher.is_active = False
        self.teacher.save(update_fields=["is_active"])

        create_tasks_for_unmarked_lessons()

        self.assertEqual({task.assigned_to for task in self._tasks()}, {self.admin})

    def test_rule_can_be_switched_off(self):
        self.org.settings = {RULE_UNMARKED_ATTENDANCE_ENABLED: False}
        self.org.save(update_fields=["settings"])
        self.assertEqual(create_tasks_for_unmarked_lessons(), 0)

    def test_task_closes_itself_when_everyone_is_marked(self):
        create_tasks_for_unmarked_lessons()
        task = self._tasks().get()
        self.assertEqual(
            client_for(self.teacher).get(f"/api/v1/tasks/{task.id}/").data["link"],
            f"/attendance?lesson={self.lesson.id}",
        )

        response = client_for(self.teacher).post(
            "/api/v1/attendance/mark-all-present/", {"lesson": str(self.lesson.id)}
        )

        self.assertEqual(response.status_code, 200, response.data)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.DONE)

    def test_partly_marked_task_stays_open(self):
        create_tasks_for_unmarked_lessons()
        task = self._tasks().get()

        client_for(self.teacher).post(
            "/api/v1/attendance/mark/",
            {"lesson": str(self.lesson.id), "child": str(self.children[0].id), "status": "present"},
        )

        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.OPEN)

    def test_nightly_run_closes_tasks_of_cancelled_lessons(self):
        create_tasks_for_unmarked_lessons()
        Lesson.objects.filter(pk=self.lesson.pk).update(status=Lesson.Status.CANCELLED)

        create_tasks_for_unmarked_lessons()

        self.assertEqual(self._tasks().get().status, Task.Status.DONE)
