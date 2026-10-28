"""История на странице «Задачи»: закрытые за период, поиск, свежие сверху."""

import datetime

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from domains.people.clients.models import Child
from domains.platform.tenants.models import Organization
from domains.platform.users.models import User

from .models import Task

URL = "/api/v1/tasks/"


class TaskHistoryTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Центр", slug="task-history")
        self.admin = User.objects.create_user(
            phone="77040000011",
            password="p",
            full_name="Админ",
            organization=self.org,
            role=User.Role.ADMIN,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def task(self, title, status, closed_days_ago=0, **extra):
        task = Task.objects.create(
            organization=self.org,
            title=title,
            status=status,
            assigned_to=self.admin,
            **extra,
        )
        # updated_at — auto_now, поэтому дату закрытия ставим через update().
        closed = timezone.now() - datetime.timedelta(days=closed_days_ago)
        Task.objects.filter(pk=task.pk).update(updated_at=closed)
        return task

    def titles(self, **params):
        response = self.client.get(URL, {"assigned_to": self.admin.id, **params})
        self.assertEqual(response.status_code, 200, response.data)
        return [row["title"] for row in response.data["results"]]

    def test_closed_returns_done_and_cancelled_newest_first(self):
        self.task("Открытая", Task.Status.OPEN)
        self.task("Старая выполненная", Task.Status.DONE, closed_days_ago=5)
        self.task("Отменённая", Task.Status.CANCELLED, closed_days_ago=1)
        self.task("Свежая выполненная", Task.Status.DONE)

        self.assertEqual(
            self.titles(status="closed", ordering="-closed"),
            ["Свежая выполненная", "Отменённая", "Старая выполненная"],
        )

    def test_closed_after_hides_older_tasks(self):
        self.task("Неделю назад", Task.Status.DONE, closed_days_ago=7)
        self.task("Вчера", Task.Status.DONE, closed_days_ago=1)
        since = (timezone.now() - datetime.timedelta(days=3)).isoformat()

        self.assertEqual(self.titles(status="closed", closed_after=since), ["Вчера"])

    def test_bad_closed_after_is_ignored(self):
        self.task("Выполненная", Task.Status.DONE, closed_days_ago=30)

        self.assertEqual(
            self.titles(status="closed", closed_after="2026-13-45T99:00"), ["Выполненная"]
        )

    def test_search_by_title_and_child_name(self):
        child = Child.objects.create(
            organization=self.org, full_name="Касымова Айлин", birth_date=datetime.date(2017, 5, 1)
        )
        self.task("Напомнить об оплате", Task.Status.DONE, child=child)
        self.task("Подготовить костюмы", Task.Status.DONE)

        self.assertEqual(self.titles(status="closed", q="айлин"), ["Напомнить об оплате"])
        self.assertEqual(self.titles(status="closed", q="КОСТЮМ"), ["Подготовить костюмы"])
