"""
Изоляция кабинета родителя (TRU-141) — блокирующий джоб CI (tag
tenant_isolation).

Тест перебирает ВСЕ маршруты кабинета (portal/urls.py). Новый эндпоинт,
которого нет в CASES, роняет сборку: сначала решить, как его проверять на
изоляцию, потом выпускать. Для каждого:
- без токена и с JWT сотрудника — не пускает;
- родитель А с идентификатором ребёнка, сессии или объявления родителя Б
  (того же центра и другого), и с несуществующим — одинаковый 404;
- в списках родителя А нет ничего о детях Б.
Плюс: ответ о ребёнке не шире согласованного списка полей.
"""

import uuid
from datetime import date

from django.test import tag
from django.urls import get_resolver
from rest_framework.test import APIClient

from domains.people.clients.models import Child, ChildContact
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group, GroupMembership

from .account import CHILD_FIELDS
from .models import Announcement, ParentAccessLog, ParentSession
from .tests_auth import MAMA, PortalAuthBase, family

STRANGER = "+77019990000"
FAR_AWAY = "+77029990000"

# Как проверять каждый маршрут кабинета. kind:
#   public — вход, токен не нужен;
#   own    — без идентификатора, отдаёт только своё;
#   child / makeup / session / announcement — идентификатор чужого объекта → 404.
CASES = {
    "request-code": ("public", "post"),
    "verify": ("public", "post"),
    "logout": ("own", "post"),
    "sessions": ("own", "get"),
    "me": ("own", "get"),
    "profile": ("own", "get"),
    "phone-change": ("own", "post"),
    "notifications": ("own", "get"),
    "push": ("own", "post"),
    "announcements": ("own", "get"),
    "child": ("child", "get"),
    "child-attendance": ("child", "get"),
    "child-schedule": ("child", "get"),
    "child-makeup": ("makeup", "get"),
    "child-lesson-request-options": ("child", "get"),
    "child-lesson-requests": ("child", "get"),
    "child-summary": ("child", "get"),
    "child-money": ("child", "get"),
    "child-parent-notes": ("child", "get"),
    "child-parent-note-read": ("child-note", "post"),
    "session-detail": ("session", "delete"),
    "announcement-read": ("announcement", "post"),
}


def portal_patterns():
    resolver = get_resolver()
    for top in resolver.url_patterns:
        for api in getattr(top, "url_patterns", []):
            if (
                getattr(api, "namespace", None) == "portal"
                or getattr(api, "app_name", None) == "portal"
            ):
                return {p.name: p for p in api.url_patterns}
    raise AssertionError("Маршруты кабинета не найдены")


@tag("tenant_isolation")
class PortalIsolationTests(PortalAuthBase):
    def setUp(self):
        super().setUp()
        # Б — другая семья того же центра; В — семья другого центра.
        _, (self.stranger_child,) = family(self.org, "Чужая Мама", STRANGER, "Чужой Ребёнок")
        far = Organization.objects.create(name="Далёкий центр", slug="far")
        _, (self.far_child,) = family(far, "Далёкая Мама", FAR_AWAY, "Далёкий Ребёнок")
        branch = Branch.objects.create(organization=self.org, name="Абая")
        direction = Direction.objects.create(organization=self.org, name="Балет")
        group = Group.objects.create(
            organization=self.org,
            branch=branch,
            direction=direction,
            name="Чужая группа",
            capacity=10,
        )
        GroupMembership.objects.create(
            organization=self.org,
            child=self.stranger_child,
            group=group,
            joined_at=date(2026, 9, 1),
        )
        admin = User.objects.create_user(
            phone="+77010000061",
            password="x",
            full_name="Админ",
            organization=self.org,
            role=User.Role.ADMIN,
        )
        self.stranger_announcement = Announcement.objects.create(
            organization=self.org,
            title="Только чужой группе",
            audience="group",
            group=group,
            status="published",
            published_at="2026-09-30T10:00:00Z",
            created_by=admin,
        )
        self.stranger_client = self.as_parent(self.login(STRANGER))
        self.stranger_session = ParentSession.objects.get(account__phone=STRANGER)
        self.mama = self.as_parent(self.login(MAMA))
        self.patterns = portal_patterns()

    def url(self, name, **kwargs):
        from django.urls import reverse

        return reverse(f"portal:{name}", kwargs=kwargs or None, current_app="portal")

    def test_every_portal_endpoint_is_covered(self):
        missing = sorted(set(self.patterns) - set(CASES))
        self.assertEqual(
            missing, [], "Новый эндпоинт кабинета — добавьте его в CASES проверки изоляции"
        )

    def test_anonymous_and_staff_tokens_are_rejected(self):
        staff_user = User.objects.create_user(
            phone="+77010000062",
            password="x",
            full_name="Владелец",
            organization=self.org,
            role=User.Role.OWNER,
        )
        staff = APIClient()
        staff.force_authenticate(staff_user)
        anonymous = APIClient()
        for name, (kind, method) in CASES.items():
            if kind == "public":
                continue
            url = self.url(name, **self.foreign_kwargs(kind))
            with self.subTest(endpoint=name):
                self.assertEqual(getattr(anonymous, method)(url).status_code, 401)
                self.assertIn(getattr(staff, method)(url).status_code, (401, 403))

    def foreign_kwargs(self, kind, which="stranger"):
        if kind in ("child", "makeup", "child-note"):
            kwargs = {
                "child_id": {
                    "stranger": self.stranger_child.id,
                    "far": self.far_child.id,
                    "missing": uuid.uuid4(),
                }[which],
            }
            if kind == "makeup":
                kwargs["attendance_id"] = uuid.uuid4()
            if kind == "child-note":
                kwargs["note_id"] = uuid.uuid4()
            return kwargs
        if kind == "session":
            return {"session_id": self.stranger_session.id if which != "missing" else uuid.uuid4()}
        if kind == "announcement":
            return {
                "announcement_id": self.stranger_announcement.id
                if which != "missing"
                else uuid.uuid4()
            }
        return {}

    def test_foreign_ids_are_indistinguishable_from_missing(self):
        for name, (kind, method) in CASES.items():
            if kind in ("public", "own"):
                continue
            missing = getattr(self.mama, method)(
                self.url(name, **self.foreign_kwargs(kind, "missing"))
            )
            for which in ("stranger", "far"):
                response = getattr(self.mama, method)(
                    self.url(name, **self.foreign_kwargs(kind, which))
                )
                with self.subTest(endpoint=name, owner=which):
                    self.assertEqual(response.status_code, 404)
                    self.assertEqual(response.content, missing.content)
                    self.assertNotIn("Чужой", response.content.decode())
        # Сессию чужого родителя не отозвать.
        self.stranger_session.refresh_from_db()
        self.assertIsNone(self.stranger_session.revoked_at)

    def test_own_endpoints_show_nothing_foreign(self):
        for name, (kind, method) in CASES.items():
            if kind != "own" or method != "get":
                continue
            body = self.mama.get(self.url(name)).content.decode()
            with self.subTest(endpoint=name):
                for secret in (
                    "Чужой Ребёнок",
                    "Чужая Мама",
                    "Далёкий",
                    STRANGER[1:],
                    "Только чужой группе",
                ):
                    self.assertNotIn(secret, body)

    def test_child_fields_are_the_agreed_list(self):
        Child.objects.filter(pk=self.child.pk).update(
            medical_notes="астма", leave_reason="дорого", consent_given=True
        )
        child = self.mama.get("/api/v1/portal/me/").data["children"][0]
        self.assertEqual(set(child), set(CHILD_FIELDS))
        self.assertEqual(
            set(self.mama.get(f"/api/v1/portal/children/{self.child.id}/").data), set(CHILD_FIELDS)
        )

    def test_unlinked_contact_closes_access_on_next_request(self):
        self.assertEqual(
            self.mama.get(f"/api/v1/portal/children/{self.child.id}/summary/").status_code, 200
        )
        ChildContact.objects.filter(child=self.child).delete()  # мягкое удаление связи
        self.assertEqual(
            self.mama.get(f"/api/v1/portal/children/{self.child.id}/summary/").status_code, 404
        )
        self.assertEqual(self.mama.get("/api/v1/portal/me/").data["children"], [])

    def test_data_requests_are_logged(self):
        self.mama.get(f"/api/v1/portal/children/{self.child.id}/money/")
        self.mama.get(
            f"/api/v1/portal/children/{self.stranger_child.id}/money/"
        )  # 404 — не пишется как просмотр
        views = ParentAccessLog.objects.filter(phone=MAMA, event=ParentAccessLog.Event.DATA_VIEW)
        self.assertEqual(
            [v.path for v in views], [f"/api/v1/portal/children/{self.child.id}/money/"]
        )
