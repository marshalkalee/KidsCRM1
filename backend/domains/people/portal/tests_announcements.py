"""
Объявления центра (TRU-140): доходят только до адресатов (центр, филиал,
направление, группа), черновик не виден, истёкшее — в архиве,
непрочитанные, права сотрудников, чужой центр.
"""

from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from domains.people.clients.models import Child
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group, GroupMembership

from .models import Announcement
from .tests_auth import MAMA, PortalAuthBase, family

GYM_MAMA = "+77031112233"


class AnnouncementsTests(PortalAuthBase):
    def setUp(self):
        super().setUp()
        self.abaya = Branch.objects.create(organization=self.org, name="Абая")
        self.orbita = Branch.objects.create(organization=self.org, name="Орбита")
        self.ballet = Direction.objects.create(organization=self.org, name="Балет")
        self.gym = Direction.objects.create(organization=self.org, name="Гимнастика")
        self.ballet_group = Group.objects.create(
            organization=self.org,
            branch=self.abaya,
            direction=self.ballet,
            name="Балет 4–9",
            capacity=12,
        )
        self.gym_group = Group.objects.create(
            organization=self.org,
            branch=self.orbita,
            direction=self.gym,
            name="Гимнастика 6–8",
            capacity=12,
        )
        self.join(self.child, self.ballet_group)  # Айлин — балет на Абая
        _, (self.gymnast,) = family(self.org, "Мама гимнастки", GYM_MAMA, "Гимнастка Алия")
        self.join(self.gymnast, self.gym_group)  # Алия — гимнастика в Орбите
        self.admin = User.objects.create_user(
            phone="+77010000058",
            password="x",
            full_name="Админ",
            organization=self.org,
            role=User.Role.ADMIN,
        )
        self.staff = APIClient()
        self.staff.force_authenticate(self.admin)

    def join(self, child, group):
        GroupMembership.objects.create(
            organization=self.org, child=child, group=group, joined_at=date(2026, 9, 1)
        )

    def announce(self, publish=True, **data):
        body = {
            "title": "Отчётный концерт",
            "body": "25 декабря",
            "audience": "organization",
            **data,
        }
        response = self.staff.post("/api/v1/announcements/", body, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        if publish:
            self.staff.post(f"/api/v1/announcements/{response.data['id']}/publish/")
        return response.data

    def titles(self, phone, archive=False):
        self.age_challenges(phone)
        client = self.as_parent(self.login(phone))
        url = "/api/v1/portal/announcements/" + ("?archive=1" if archive else "")
        return [row["title"] for row in client.get(url).data["results"]]

    def test_reaches_only_its_audience(self):
        self.announce(title="Всем")
        self.announce(title="Абая", audience="branch", branch=str(self.abaya.id))
        self.announce(title="Гимнастика", audience="direction", direction=str(self.gym.id))
        self.announce(title="Группа балета", audience="group", group=str(self.ballet_group.id))
        self.assertEqual(sorted(self.titles(MAMA)), ["Абая", "Всем", "Группа балета"])
        self.assertEqual(sorted(self.titles(GYM_MAMA)), ["Всем", "Гимнастика"])

    def test_direction_from_child_card_counts(self):
        Child.objects.get(pk=self.child.pk).directions.add(self.gym)
        self.announce(title="Гимнастика", audience="direction", direction=str(self.gym.id))
        self.assertEqual(self.titles(MAMA), ["Гимнастика"])

    def test_draft_and_left_children_see_nothing(self):
        self.announce(title="Черновик", publish=False)
        self.assertEqual(self.titles(MAMA), [])
        self.announce(title="Всем")
        Child.objects.filter(pk=self.child.pk).update(status="left")
        self.assertEqual(self.titles(MAMA), [])

    def test_expired_goes_to_archive(self):
        self.announce(title="Старое", expires_on=str(date.today() - timedelta(days=1)))
        self.announce(title="Сегодня последний день", expires_on=str(date.today()))
        self.assertEqual(self.titles(MAMA), ["Сегодня последний день"])
        self.assertEqual(self.titles(MAMA, archive=True), ["Старое"])

    def test_unread_count_and_mark_read(self):
        first = self.announce(title="Первое")
        self.announce(title="Второе")
        client = self.as_parent(self.login())
        self.assertEqual(client.get("/api/v1/portal/announcements/").data["unread"], 2)
        self.assertEqual(
            client.post(f"/api/v1/portal/announcements/{first['id']}/read/").status_code, 204
        )
        client.post(f"/api/v1/portal/announcements/{first['id']}/read/")  # повтор не ломает
        data = client.get("/api/v1/portal/announcements/").data
        self.assertEqual(data["unread"], 1)
        self.assertEqual(
            {r["title"]: r["read"] for r in data["results"]}, {"Первое": True, "Второе": False}
        )

    def test_cannot_read_announcement_for_other_audience(self):
        other = self.announce(title="Гимнастика", audience="group", group=str(self.gym_group.id))
        client = self.as_parent(self.login())
        self.assertEqual(
            client.post(f"/api/v1/portal/announcements/{other['id']}/read/").status_code, 404
        )

    def test_unpublish_hides_from_parents(self):
        item = self.announce(title="Ошибочное")
        self.staff.post(f"/api/v1/announcements/{item['id']}/unpublish/")
        self.assertEqual(self.titles(MAMA), [])

    def test_reach_counts_children(self):
        self.assertEqual(self.announce()["reach"], 2)
        self.assertEqual(
            self.announce(audience="group", group=str(self.ballet_group.id))["reach"], 1
        )

    def test_target_required_and_extra_targets_cleared(self):
        response = self.staff.post(
            "/api/v1/announcements/", {"title": "x", "audience": "group"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("group", response.data)
        item = self.announce(
            audience="branch", branch=str(self.abaya.id), group=str(self.ballet_group.id)
        )
        self.assertIsNone(Announcement.objects.get(pk=item["id"]).group)

    def test_teacher_cannot_manage(self):
        teacher = User.objects.create_user(
            phone="+77010000059",
            password="x",
            full_name="Педагог",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        client = APIClient()
        client.force_authenticate(teacher)
        self.assertEqual(
            client.post("/api/v1/announcements/", {"title": "x"}, format="json").status_code, 403
        )

    def test_foreign_center_targets_rejected_and_invisible(self):
        other = Organization.objects.create(name="Чужой", slug="other")
        foreign_branch = Branch.objects.create(organization=other, name="Чужой филиал")
        response = self.staff.post(
            "/api/v1/announcements/",
            {"title": "x", "audience": "branch", "branch": str(foreign_branch.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        other_admin = User.objects.create_user(
            phone="+77010000060",
            password="x",
            full_name="Чужой",
            organization=other,
            role=User.Role.ADMIN,
        )
        foreign = APIClient()
        foreign.force_authenticate(other_admin)
        foreign_item = foreign.post(
            "/api/v1/announcements/", {"title": "Чужое"}, format="json"
        ).data
        foreign.post(f"/api/v1/announcements/{foreign_item['id']}/publish/")
        self.assertEqual(self.titles(MAMA), [])
        self.assertEqual(
            self.staff.get(f"/api/v1/announcements/{foreign_item['id']}/").status_code, 404
        )

    def test_attachment_types_and_size(self):
        pdf = SimpleUploadedFile("Афиша.pdf", b"%PDF-1.4 test", content_type="application/pdf")
        ok = self.staff.post("/api/v1/announcements/attachment/", {"file": pdf}, format="multipart")
        self.assertEqual(ok.status_code, 201, ok.data)
        self.assertEqual(ok.data["name"], "Афиша.pdf")
        self.assertIn("/media/announcements/", ok.data["url"])
        exe = SimpleUploadedFile("virus.exe", b"MZ", content_type="application/octet-stream")
        self.assertEqual(
            self.staff.post(
                "/api/v1/announcements/attachment/", {"file": exe}, format="multipart"
            ).status_code,
            400,
        )

    def test_published_at_set_once(self):
        item = self.announce()
        first = Announcement.objects.get(pk=item["id"]).published_at
        self.staff.post(f"/api/v1/announcements/{item['id']}/publish/")
        self.assertEqual(Announcement.objects.get(pk=item["id"]).published_at, first)
        self.assertLessEqual(first, timezone.now())
