"""
Вход родителя по телефону и паролю (Д40): пароль выдаёт администратор,
неразглашение номера, лимиты неудачных попыток, смена пароля, сессии,
изоляция от API сотрудников, аудит.
"""

from datetime import date, timedelta

from django.test import TestCase, tag
from django.utils import timezone
from rest_framework.test import APIClient

from domains.people.clients.models import Child, ChildContact, ContactPhone, ParentContact
from domains.platform.core.audit import AuditLog
from domains.platform.tenants.models import Branch, Organization
from domains.platform.users.models import User

from . import auth
from .models import ParentAccessLog, ParentAccount, ParentSession

MAMA = "+77011234567"


def family(org, parent_name, phone, *children, whatsapp=""):
    parent = ParentContact.objects.create(
        organization=org, full_name=parent_name, whatsapp=whatsapp
    )
    if phone:
        ContactPhone.objects.create(parent_contact=parent, number=phone)
    kids = []
    for name in children:
        child = Child.objects.create(organization=org, full_name=name, birth_date=date(2017, 5, 1))
        ChildContact.objects.create(
            organization=org, child=child, parent_contact=parent, role="mother"
        )
        kids.append(child)
    return parent, kids


class PortalAuthBase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="tb")
        Branch.objects.create(organization=self.org, name="Алмалы")
        self.parent, (self.child,) = family(self.org, "Касымова Гульмира", MAMA, "Касымова Айлин")
        self.api = APIClient()
        self.passwords = {}

    def password_for(self, phone=MAMA):
        """Пароль выдаётся один раз на номер — повторная выдача закрыла бы входы."""
        if phone not in self.passwords:
            self.passwords[phone] = auth.issue_password(phone)
        return self.passwords[phone]

    def attempt(self, phone=MAMA, password=None, ip="10.0.0.1"):
        return self.api.post(
            "/api/v1/portal/auth/login/",
            {
                "phone": phone,
                "password": self.password_for(phone) if password is None else password,
            },
            REMOTE_ADDR=ip,
        )

    def login(self, phone=MAMA):
        response = self.attempt(phone)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["token"]

    def as_parent(self, token):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Parent {token}")
        return client

    def age_challenges(self, phone=MAMA, by=timedelta(minutes=2)):
        """Со входа по коду: теперь ждать нечего — оставлено для старых тестов."""


class LoginFlowTests(PortalAuthBase):
    def test_phone_password_session_children(self):
        self.password_for(MAMA)
        response = self.attempt("8 701 123 45 67", self.passwords[MAMA])  # нормализуется
        self.assertEqual(response.status_code, 200, response.data)
        me = self.as_parent(response.data["token"]).get("/api/v1/portal/me/").data
        self.assertEqual([c["full_name"] for c in me["children"]], ["Касымова Айлин"])
        self.assertEqual(me["phone"], MAMA)

    def test_whatsapp_number_also_works(self):
        family(self.org, "Папа", None, "Ахметов Тимур", whatsapp="+77079998877")
        token = self.login("+77079998877")
        names = [
            c["full_name"] for c in self.as_parent(token).get("/api/v1/portal/me/").data["children"]
        ]
        self.assertEqual(names, ["Ахметов Тимур"])

    def test_password_is_stored_only_as_hash_and_is_readable(self):
        password = self.password_for()
        self.assertEqual(len(password), auth.ISSUED_LENGTH)
        self.assertFalse(set(password) & set("0O1lI"))  # без похожих символов
        stored = ParentAccount.objects.get(phone=MAMA).password
        self.assertNotIn(password, stored)
        self.assertTrue(stored.startswith(("pbkdf2_", "argon2", "bcrypt")))

    def test_new_password_closes_previous_sessions(self):
        token = self.login()
        auth.issue_password(MAMA)
        self.assertEqual(self.as_parent(token).get("/api/v1/portal/me/").status_code, 401)


class NoDisclosureTests(PortalAuthBase):
    def test_same_answer_for_wrong_password_unknown_phone_and_no_password(self):
        self.password_for()
        family(self.org, "Без пароля", "+77015550000", "Ребёнок")
        answers = [
            self.attempt(MAMA, "неверный"),
            self.attempt("+77779998877", "что-то"),
            self.attempt("+77015550000", "что-то"),
        ]
        self.assertEqual({r.status_code for r in answers}, {400})
        self.assertEqual({r.data["detail"] for r in answers}, {auth.WRONG_LOGIN})

    def test_password_for_unknown_phone_cannot_be_issued(self):
        with self.assertRaises(auth.LoginError):
            auth.issue_password("+77779998877")


class RateLimitTests(PortalAuthBase):
    def test_failed_attempts_per_phone(self):
        for _ in range(auth.FAILED_PER_PHONE):
            self.assertEqual(self.attempt(password="неверный").status_code, 400)
        blocked = self.attempt()  # даже верный пароль — после лимита ждать
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Retry-After", blocked)

    def test_failed_attempts_per_ip(self):
        for n in range(auth.FAILED_PER_IP):
            self.attempt(f"+7701000{n:04d}", "что-то", ip="10.0.0.9")
        self.assertEqual(self.attempt(ip="10.0.0.9").status_code, 429)

    def test_bad_phone_is_explained(self):
        response = self.attempt("123", "что-то")
        self.assertEqual(response.status_code, 400)
        self.assertIn("номер", response.data["detail"])


class PasswordChangeTests(PortalAuthBase):
    def test_change_needs_current_and_closes_other_devices(self):
        here = self.as_parent(self.login())
        other = self.as_parent(self.login())
        url = "/api/v1/portal/profile/password/"
        self.assertEqual(
            here.post(url, {"current": "не тот", "new": "новый-пароль"}).status_code, 400
        )
        self.assertEqual(
            here.post(url, {"current": self.passwords[MAMA], "new": "коротко"}).status_code, 400
        )
        ok = here.post(url, {"current": self.passwords[MAMA], "new": "новый-пароль"})
        self.assertEqual(ok.status_code, 200, ok.data)
        self.assertEqual(here.get("/api/v1/portal/me/").status_code, 200)
        self.assertEqual(other.get("/api/v1/portal/me/").status_code, 401)
        self.assertEqual(self.attempt(password="новый-пароль").status_code, 200)


class SessionTests(PortalAuthBase):
    def test_logout_and_logout_everywhere(self):
        phone_token = self.login()
        self.age_challenges()
        laptop_token = self.login()
        phone, laptop = self.as_parent(phone_token), self.as_parent(laptop_token)

        sessions = phone.get("/api/v1/portal/auth/sessions/").data
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sum(s["current"] for s in sessions), 1)

        self.assertEqual(laptop.post("/api/v1/portal/auth/logout/").status_code, 204)
        self.assertEqual(laptop.get("/api/v1/portal/me/").status_code, 401)
        self.assertEqual(phone.get("/api/v1/portal/me/").status_code, 200)

        self.age_challenges()
        third = self.as_parent(self.login())
        third.post("/api/v1/portal/auth/logout/", {"everywhere": True}, format="json")
        self.assertEqual(phone.get("/api/v1/portal/me/").status_code, 401)
        self.assertEqual(ParentSession.objects.filter(revoked_at__isnull=True).count(), 0)

    def test_revoke_lost_device(self):
        first = self.as_parent(self.login())
        self.age_challenges()
        second_token = self.login()
        lost = next(s for s in first.get("/api/v1/portal/auth/sessions/").data if not s["current"])
        self.assertEqual(
            first.delete(f"/api/v1/portal/auth/sessions/{lost['id']}/").status_code, 204
        )
        self.assertEqual(self.as_parent(second_token).get("/api/v1/portal/me/").status_code, 401)

    def test_expired_session(self):
        client = self.as_parent(self.login())
        ParentSession.objects.update(expires_at=timezone.now())
        self.assertEqual(client.get("/api/v1/portal/me/").status_code, 401)

    def test_session_is_extended_while_used(self):
        client = self.as_parent(self.login())
        ParentSession.objects.update(
            last_seen_at=timezone.now() - timedelta(days=10),
            expires_at=timezone.now() + timedelta(days=80),
        )
        client.get("/api/v1/portal/me/")
        session = ParentSession.objects.get()
        self.assertGreater(
            session.expires_at, timezone.now() + timedelta(days=auth.SESSION_DAYS - 1)
        )


class AccessTests(PortalAuthBase):
    def test_children_in_two_branches_and_two_centers(self):
        Branch.objects.create(organization=self.org, name="Орбита")
        sister = Child.objects.create(
            organization=self.org, full_name="Касымова Адель", birth_date=date(2015, 3, 1)
        )
        ChildContact.objects.create(
            organization=self.org, child=sister, parent_contact=self.parent, role="mother"
        )
        other_center = Organization.objects.create(name="Gym Kids", slug="gym")
        family(other_center, "Касымова Гульмира", MAMA, "Касымов Арман")
        me = self.as_parent(self.login()).get("/api/v1/portal/me/").data
        self.assertEqual(
            sorted((c["full_name"], c["organization"]["name"]) for c in me["children"]),
            [
                ("Касымов Арман", "Gym Kids"),
                ("Касымова Адель", "True Ballet"),
                ("Касымова Айлин", "True Ballet"),
            ],
        )

    def test_unlinked_contact_loses_access_immediately(self):
        client = self.as_parent(self.login())
        ChildContact.objects.filter(child=self.child).update(deleted_at=timezone.now())
        self.assertEqual(client.get("/api/v1/portal/me/").data["children"], [])

    @tag("tenant_isolation")
    def test_parent_token_does_not_open_staff_api(self):
        _, (stranger,) = family(self.org, "Чужая мама", "+77019990000", "Чужой Ребёнок")
        client = self.as_parent(self.login())
        for url in (
            "/api/v1/clients/children/",
            f"/api/v1/clients/children/{stranger.id}/card/",
            f"/api/v1/clients/children/{self.child.id}/card/",
            "/api/v1/payments/",
            "/api/v1/users/auth/me/",
        ):
            with self.subTest(url=url):
                self.assertEqual(client.get(url).status_code, 401)
        names = [c["full_name"] for c in client.get("/api/v1/portal/me/").data["children"]]
        self.assertNotIn("Чужой Ребёнок", names)

    @tag("tenant_isolation")
    def test_staff_jwt_does_not_open_portal(self):
        owner = User.objects.create_user(
            phone="+77010000001",
            password="x",
            full_name="Владелец",
            organization=self.org,
            role=User.Role.OWNER,
        )
        staff = APIClient()
        staff.force_authenticate(owner)
        self.assertIn(staff.get("/api/v1/portal/me/").status_code, (401, 403))

    def test_login_is_audited_in_each_center(self):
        other_center = Organization.objects.create(name="Gym Kids", slug="gym")
        family(other_center, "Касымова Гульмира", MAMA, "Касымов Арман")
        self.login()
        audits = AuditLog.objects.filter(action=AuditLog.Action.PARENT_LOGIN)
        self.assertEqual({a.organization_id for a in audits}, {self.org.id, other_center.id})
        self.assertIsNone(audits.first().actor)
        self.assertTrue(
            ParentAccessLog.objects.filter(event=ParentAccessLog.Event.LOGIN, phone=MAMA).exists()
        )


class StaffIssuesPasswordTests(PortalAuthBase):
    """Пароль выдаёт администратор в карточке родителя (Д40)."""

    def staff(self, role, phone):
        user = User.objects.create_user(
            phone=phone, password="x", full_name=role, organization=self.org, role=role
        )
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_admin_issues_password_parent_logs_in(self):
        admin = self.staff(User.Role.ADMIN, "+77010000301")
        url = f"/api/v1/clients/parents/{self.parent.id}/portal-access/"
        self.assertFalse(admin.get(url).data["has_password"])
        issued = admin.post(url).data
        self.assertEqual(issued["phone"], MAMA)
        self.assertIn(issued["password"], issued["message"])
        self.assertTrue(issued["whatsapp_url"].startswith("https://wa.me/"))
        self.assertEqual(self.attempt(MAMA, issued["password"]).status_code, 200)
        self.assertTrue(admin.get(url).data["has_password"])

    def test_teacher_cannot_issue_password(self):
        teacher = self.staff(User.Role.TEACHER, "+77010000302")
        url = f"/api/v1/clients/parents/{self.parent.id}/portal-access/"
        self.assertEqual(teacher.post(url).status_code, 403)
