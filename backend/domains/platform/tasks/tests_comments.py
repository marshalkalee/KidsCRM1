"""Комментарии и лента карточки задачи (TRU-184)."""

import datetime

from django.test import TestCase, tag
from django.utils import timezone
from rest_framework.test import APIClient

from domains.platform.tenants.models import Branch, Organization
from domains.platform.users.models import User

from .models import Task, TaskComment
from .services import create_task

URL = "/api/v1/tasks/"


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


class CommentFixtures(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Центр", slug="task-comments")
        self.a = Branch.objects.create(organization=self.org, name="Алмалы")
        self.b = Branch.objects.create(organization=self.org, name="Орбита")
        self.owner = self.user("77050000001", "Владелец", User.Role.OWNER)
        self.anel = self.user("77050000002", "Анель", User.Role.ADMIN, [self.a])
        self.darya = self.user("77050000003", "Дарья", User.Role.ADMIN, [self.a])
        self.admin_b = self.user("77050000004", "Админ Орбиты", User.Role.ADMIN, [self.b])
        self.teacher = self.user("77050000005", "Преподаватель", User.Role.TEACHER)
        self.task = Task.objects.create(
            organization=self.org,
            title="Перезвонить маме",
            assigned_to=self.anel,
            created_by=self.owner,
            branch=self.a,
            due_at=timezone.now() + datetime.timedelta(hours=2),
        )

    def user(self, phone, name, role, branches=()):
        user = User.objects.create_user(
            phone=phone, password="p", full_name=name, organization=self.org, role=role
        )
        user.branches.set(branches)
        return user

    def comment(self, user, text, task=None):
        task = task or self.task
        return client_for(user).post(f"{URL}{task.id}/comments/", {"text": text}, format="json")

    def timeline(self, user, task=None):
        task = task or self.task
        response = client_for(user).get(f"{URL}{task.id}/timeline/")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["items"]


class CommentTests(CommentFixtures):
    def test_comment_and_handover_seen_by_new_assignee(self):
        """Критерий приёмки: «не взяли трубку» + передача коллеге."""
        response = self.comment(self.anel, "не взяли трубку")
        self.assertEqual(response.status_code, 201, response.data)
        handover = client_for(self.anel).patch(
            f"{URL}{self.task.id}/", {"assigned_to": str(self.darya.id)}, format="json"
        )
        self.assertEqual(handover.status_code, 200, handover.data)

        texts = [item["text"] for item in self.timeline(self.darya)]
        self.assertEqual(
            texts,
            [
                "Задача создана, исполнитель: Анель",
                "не взяли трубку",
                "Задача передана: Анель → Дарья",
            ],
        )
        items = self.timeline(self.darya)
        self.assertEqual(items[1]["kind"], "comment")
        self.assertEqual(items[1]["author_name"], "Анель")
        self.assertEqual(items[2]["author_name"], "Анель")

    def test_due_date_moved_and_completed(self):
        tz = datetime.timezone(datetime.timedelta(hours=5))
        due = datetime.datetime(2026, 10, 14, 23, 59, tzinfo=tz)
        self.org.timezone = "Asia/Almaty"
        self.org.save()
        client = client_for(self.anel)
        client.patch(f"{URL}{self.task.id}/", {"due_at": due.isoformat()}, format="json")
        client.post(f"{URL}{self.task.id}/complete/", {"comment": "записали"}, format="json")
        texts = [item["text"] for item in self.timeline(self.anel)]
        self.assertIn("Срок перенесён на 14.10", texts)
        self.assertEqual(texts[-1], "Выполнена: «записали»")

    def test_title_change_is_not_in_timeline(self):
        client_for(self.anel).patch(f"{URL}{self.task.id}/", {"title": "Новое"}, format="json")
        self.assertEqual(len(self.timeline(self.anel)), 1)

    def test_closed_outside_api_still_shown(self):
        """Запрос родителя закрывает задачу через update() мимо журнала."""
        Task.objects.filter(pk=self.task.pk).update(
            status=Task.Status.DONE, closing_comment="Записан на занятие"
        )
        texts = [item["text"] for item in self.timeline(self.anel)]
        self.assertEqual(texts[-1], "Выполнена: «Записан на занятие»")

    def test_automatic_task(self):
        task = create_task(
            type=Task.Type.PAYMENT_REMINDER,
            assignee=None,
            due_date=None,
            subject="Напомнить об оплате",
            organization=self.org,
            source=Task.Source.AUTO,
            source_key="debt_reminder:1",
        )
        self.assertEqual(
            self.timeline(self.owner, task)[0]["text"],
            "Создана автоматически: просроченный долг",
        )
        no_show = Task.objects.create(
            organization=self.org,
            type=Task.Type.TRIAL_NO_SHOW,
            title="Перезвонить: не пришёл на пробное",
            source_key="attendance:1",
        )
        self.assertEqual(
            self.timeline(self.owner, no_show)[0]["text"],
            "Создана автоматически: не пришёл на пробное",
        )

    def test_text_validation(self):
        self.assertEqual(self.comment(self.anel, "   ").status_code, 400)
        self.assertEqual(self.comment(self.anel, "я" * 2001).status_code, 400)
        self.assertEqual(self.comment(self.anel, "я" * 2000).status_code, 201)

    def test_comments_count_in_list(self):
        self.comment(self.anel, "раз")
        self.comment(self.owner, "два")
        deleted = self.comment(self.anel, "три").data["id"]
        client_for(self.anel).delete(f"{URL}{self.task.id}/comments/{deleted}/")
        rows = client_for(self.anel).get(URL, {"assigned_to": self.anel.id}).data
        rows = rows["results"] if isinstance(rows, dict) else rows
        self.assertEqual(rows[0]["comments_count"], 2)
        detail = client_for(self.anel).get(f"{URL}{self.task.id}/").data
        self.assertEqual(detail["comments_count"], 2)


class EditCommentTests(CommentFixtures):
    def setUp(self):
        super().setUp()
        self.own = self.comment(self.anel, "не взяли трубку").data
        self.url = f"{URL}{self.task.id}/comments/{self.own['id']}/"

    def test_author_edits_and_deletes_within_window(self):
        self.assertTrue(self.own["can_edit"])
        response = client_for(self.anel).patch(self.url, {"text": "сбросили"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["edited"])
        self.assertEqual(client_for(self.anel).delete(self.url).status_code, 204)
        self.assertFalse(TaskComment.objects.filter(pk=self.own["id"]).exists())
        self.assertEqual(len(self.timeline(self.anel)), 1)

    def test_not_author(self):
        listed = client_for(self.owner).get(f"{URL}{self.task.id}/comments/").data
        self.assertFalse(listed[0]["can_edit"])
        self.assertEqual(
            client_for(self.owner).patch(self.url, {"text": "x"}, format="json").status_code, 403
        )
        self.assertEqual(client_for(self.owner).delete(self.url).status_code, 403)

    def test_window_is_15_minutes(self):
        TaskComment.objects.filter(pk=self.own["id"]).update(
            created_at=timezone.now() - datetime.timedelta(minutes=16)
        )
        self.assertEqual(
            client_for(self.anel).patch(self.url, {"text": "x"}, format="json").status_code, 403
        )
        self.assertEqual(client_for(self.anel).delete(self.url).status_code, 403)


class CommentNotificationTests(CommentFixtures):
    def notification(self, user):
        items = client_for(user).get("/api/v1/notifications/").data["items"]
        return {item["kind"]: item for item in items}["task_comments"]

    def test_assignee_notified_about_colleague_comment(self):
        self.comment(self.anel, "сама себе")
        self.assertEqual(self.notification(self.anel)["count"], 0)
        self.comment(self.owner, "что сказала мама?")
        item = self.notification(self.anel)
        self.assertEqual((item["count"], item["unread"]), (1, True))
        self.assertEqual(item["link"], f"/tasks?open={self.task.id}")
        # Автору комментария уведомление не приходит: задача не его.
        self.assertEqual(self.notification(self.owner)["count"], 0)

    def test_after_handover_old_assignee_is_not_notified(self):
        self.comment(self.owner, "что сказала мама?")
        Task.objects.filter(pk=self.task.pk).update(assigned_to=self.darya)
        self.assertEqual(self.notification(self.anel)["count"], 0)
        self.assertEqual(self.notification(self.darya)["count"], 1)


@tag("tenant_isolation")
class CommentIsolationTests(CommentFixtures):
    def test_other_branch_cannot_read_or_comment(self):
        for path in ("comments/", "timeline/"):
            response = client_for(self.admin_b).get(f"{URL}{self.task.id}/{path}")
            self.assertEqual(response.status_code, 404)
        self.assertEqual(self.comment(self.admin_b, "чужое").status_code, 404)
        self.assertFalse(TaskComment.objects.exists())

    def test_teacher_only_own_tasks(self):
        self.assertEqual(self.comment(self.teacher, "чужое").status_code, 404)
        own = Task.objects.create(
            organization=self.org, title="Фото с открытого урока", assigned_to=self.teacher
        )
        self.assertEqual(self.comment(self.teacher, "отправила", own).status_code, 201)

    def test_other_organization(self):
        other = Organization.objects.create(name="Другой", slug="task-comments-other")
        stranger = User.objects.create_user(
            phone="77050000099",
            password="p",
            full_name="Чужой владелец",
            organization=other,
            role=User.Role.OWNER,
        )
        comment = self.comment(self.anel, "наше").data
        client = client_for(stranger)
        self.assertEqual(client.get(f"{URL}{self.task.id}/comments/").status_code, 404)
        self.assertEqual(client.get(f"{URL}{self.task.id}/timeline/").status_code, 404)
        self.assertEqual(self.comment(stranger, "чужое").status_code, 404)
        url = f"{URL}{self.task.id}/comments/{comment['id']}/"
        self.assertEqual(client.delete(url).status_code, 404)
        self.assertEqual(TaskComment.objects.count(), 1)
        # И в колокольчик чужой организации ничего не попадает.
        items = client.get("/api/v1/notifications/").data["items"]
        self.assertEqual({i["kind"]: i for i in items}["task_comments"]["count"], 0)

    def test_comment_of_other_task_not_reachable_by_url(self):
        """id комментария чужой задачи в адресе своей задачи — 404."""
        foreign = Task.objects.create(organization=self.org, title="Орбита", branch=self.b)
        comment = TaskComment.objects.create(
            organization=self.org, task=foreign, author=self.anel, text="x"
        )
        url = f"{URL}{self.task.id}/comments/{comment.id}/"
        self.assertEqual(client_for(self.anel).delete(url).status_code, 404)
