"""
Вход родителя по коду (TRU-135): полный путь, неразглашение номера,
лимиты, одноразовость кода, сессии, изоляция от API сотрудников, аудит.
Отправка кода подменена — код перехватываем.
"""

from datetime import date, timedelta
from unittest import mock

from django.test import TestCase, tag
from django.utils import timezone
from rest_framework.test import APIClient

from domains.people.clients.models import Child, ChildContact, ContactPhone, ParentContact
from domains.platform.core.audit import AuditLog
from domains.platform.tenants.models import Branch, Organization
from domains.platform.users.models import User

from . import auth
from .models import OtpChallenge, ParentAccessLog, ParentSession

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
        self.sent = []
        patcher = mock.patch.object(
            auth, "dispatch_code", side_effect=lambda phone, code: self.sent.append((phone, code))
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def request_code(self, phone=MAMA, ip="10.0.0.1"):
        with self.captureOnCommitCallbacks(execute=True):
            return self.api.post(
                "/api/v1/portal/auth/request-code/", {"phone": phone}, REMOTE_ADDR=ip
            )

    def verify(self, code, phone=MAMA):
        return self.api.post("/api/v1/portal/auth/verify/", {"phone": phone, "code": code})

    def login(self, phone=MAMA):
        self.request_code(phone)
        response = self.verify(self.sent[-1][1], phone)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["token"]

    def as_parent(self, token):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Parent {token}")
        return client

    def age_challenges(self, phone=MAMA, by=timedelta(minutes=2)):
        for challenge in OtpChallenge.objects.filter(phone=phone):
            OtpChallenge.objects.filter(pk=challenge.pk).update(
                created_at=challenge.created_at - by
            )


class LoginFlowTests(PortalAuthBase):
    def test_phone_code_session_children(self):
        self.request_code("8 701 123 45 67")  # нормализуется как везде в CRM
        self.assertEqual(self.sent[0][0], MAMA)
        self.assertEqual(len(self.sent[0][1]), auth.CODE_LENGTH)
        token = self.login()
        me = self.as_parent(token).get("/api/v1/portal/me/").data
        self.assertEqual([c["full_name"] for c in me["children"]], ["Касымова Айлин"])
        self.assertEqual(me["phone"], MAMA)

    def test_whatsapp_number_also_works(self):
        family(self.org, "Папа", None, "Ахметов Тимур", whatsapp="+77079998877")
        token = self.login("+77079998877")
        names = [
            c["full_name"] for c in self.as_parent(token).get("/api/v1/portal/me/").data["children"]
        ]
        self.assertEqual(names, ["Ахметов Тимур"])

    def test_code_is_single_use_and_expires(self):
        self.request_code()
        code = self.sent[-1][1]
        self.assertEqual(self.verify(code).status_code, 200)
        self.assertEqual(self.verify(code).status_code, 400)

        self.age_challenges()
        self.request_code()
        OtpChallenge.objects.filter(used_at__isnull=True).update(expires_at=timezone.now())
        self.assertEqual(self.verify(self.sent[-1][1]).status_code, 400)

    def test_code_is_stored_only_as_hash(self):
        self.request_code()
        code = self.sent[-1][1]
        challenge = OtpChallenge.objects.get()
        self.assertNotIn(code, challenge.code_hash)


class NoDisclosureTests(PortalAuthBase):
    def test_same_answer_for_known_and_unknown_phone(self):
        known = self.request_code(MAMA)
        unknown = self.request_code("+77770000099")
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known.data["detail"], unknown.data["detail"])
        self.assertEqual(set(known.data), set(unknown.data))
        # Код уходит только на известный номер — за неизвестные не платим.
        self.assertEqual([phone for phone, _ in self.sent], [MAMA])

    def test_unknown_phone_cannot_log_in_and_errors_match(self):
        self.request_code("+77770000099")
        unknown = self.verify("123456", phone="+77770000099")
        self.request_code(MAMA)
        wrong = self.verify("000000" if self.sent[-1][1] != "000000" else "111111")
        self.assertEqual(unknown.status_code, wrong.status_code)
        self.assertEqual(unknown.data, wrong.data)

    def test_limits_are_the_same_for_unknown_phone(self):
        self.request_code("+77770000099")
        self.assertEqual(self.request_code("+77770000099").status_code, 429)


class RateLimitTests(PortalAuthBase):
    def test_resend_not_sooner_than_a_minute(self):
        self.assertEqual(self.request_code().status_code, 200)
        again = self.request_code()
        self.assertEqual(again.status_code, 429)
        self.assertTrue(again["Retry-After"])
        self.assertEqual(len(self.sent), 1)

    def test_codes_per_hour_per_phone(self):
        for _ in range(auth.CODES_PER_HOUR):
            self.assertEqual(self.request_code().status_code, 200)
            self.age_challenges()
        response = self.request_code()
        self.assertEqual(response.status_code, 429)
        self.assertIn("мин", response.data["detail"])
        self.assertTrue(
            ParentAccessLog.objects.filter(event=ParentAccessLog.Event.CODE_RATE_LIMITED).exists()
        )

    def test_codes_per_hour_per_ip(self):
        for i in range(auth.IP_CODES_PER_HOUR):
            self.assertEqual(self.request_code(f"+7770000{i:04d}", ip="10.9.9.9").status_code, 200)
        self.assertEqual(self.request_code("+77771112233", ip="10.9.9.9").status_code, 429)
        self.assertEqual(self.request_code("+77771112233", ip="10.9.9.10").status_code, 200)

    def test_wrong_attempts_burn_the_code(self):
        self.request_code()
        code = self.sent[-1][1]
        wrong = "000000" if code != "000000" else "111111"
        for left in range(auth.MAX_ATTEMPTS - 1, 0, -1):
            response = self.verify(wrong)
            self.assertIn(str(left), response.data["detail"])
        self.assertIn("слишком много", self.verify(wrong).data["detail"])
        self.assertEqual(self.verify(code).status_code, 400)  # верный код уже не поможет
        self.assertEqual(
            ParentAccessLog.objects.filter(event=ParentAccessLog.Event.LOGIN_FAILED).count(), 6
        )

    def test_bad_phone_is_explained(self):
        response = self.api.post("/api/v1/portal/auth/request-code/", {"phone": "мама"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("номер", response.data["detail"])


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
