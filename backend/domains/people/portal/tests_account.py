"""
Аккаунт родителя (TRU-136): дети в разных филиалах, три случая из тикета
(мама и папа, плательщик, ушедший ребёнок), профиль, смена телефона
через код.
"""

from datetime import date, timedelta

from django.utils import timezone

from domains.people.clients.models import Child, ChildContact, ContactPhone
from domains.platform.core.audit import AuditLog
from domains.platform.tenants.models import Branch, Direction
from domains.scheduling.groups.models import Group, GroupMembership

from .models import OtpChallenge, ParentAccount
from .tests_auth import MAMA, PortalAuthBase, family

PAPA = "+77027654321"


class ParentAccountTests(PortalAuthBase):
    def group(self, branch_name, name):
        branch = Branch.objects.create(organization=self.org, name=branch_name)
        direction = Direction.objects.create(organization=self.org, name="Балет")
        return Group.objects.create(
            organization=self.org, branch=branch, direction=direction, name=name, capacity=12
        )

    def join(self, child, group):
        GroupMembership.objects.create(
            organization=self.org, child=child, group=group, joined_at=date(2026, 9, 1)
        )

    def ask_change(self, client, phone):
        with self.captureOnCommitCallbacks(execute=True):
            return client.post("/api/v1/portal/profile/phone/", {"phone": phone}, format="json")

    def me(self, phone=MAMA):
        return self.as_parent(self.login(phone)).get("/api/v1/portal/me/").data

    def test_children_in_different_branches_with_groups(self):
        sister = Child.objects.create(
            organization=self.org, full_name="Касымова Адель", birth_date=date(2015, 3, 1)
        )
        ChildContact.objects.create(
            organization=self.org, child=sister, parent_contact=self.parent, role="mother"
        )
        self.join(self.child, self.group("Алмалы-2", "Балет 6–9"))
        self.join(sister, self.group("Орбита", "Балет 10–14"))
        kids = {c["full_name"]: c for c in self.me()["children"]}
        self.assertEqual(kids["Касымова Айлин"]["branches"], ["Алмалы-2"])
        self.assertEqual(kids["Касымова Адель"]["groups"][0]["name"], "Балет 10–14")
        self.assertEqual(kids["Касымова Адель"]["branches"], ["Орбита"])

    def test_case1_mother_and_father_see_the_same_child(self):
        _, _ = family(self.org, "Касымов Ерлан", PAPA, "Касымова Айлин")
        papa_contact = ChildContact.objects.filter(
            parent_contact__full_name="Касымов Ерлан"
        ).first()
        extra_child = papa_contact.child
        # Папа привязан к тому же ребёнку, что и мама (а не к однофамильцу).
        papa_contact.child = self.child
        papa_contact.save()
        extra_child.delete()
        mama = self.me(MAMA)["children"]
        self.age_challenges()
        papa = self.me(PAPA)["children"]
        self.assertEqual(mama, papa)

    def test_case2_payer_and_contact_both_have_access(self):
        grandma, _ = family(self.org, "Бабушка", "+77051112233")
        ChildContact.objects.create(
            organization=self.org,
            child=self.child,
            parent_contact=grandma,
            role="grandmother",
            is_payer=True,
        )
        names = [c["full_name"] for c in self.me("+77051112233")["children"]]
        self.assertEqual(names, ["Касымова Айлин"])
        self.age_challenges()
        self.assertEqual([c["full_name"] for c in self.me(MAMA)["children"]], ["Касымова Айлин"])

    def test_case3_left_child_stays_visible_last(self):
        sister = Child.objects.create(
            organization=self.org, full_name="Абаева Аружан", birth_date=date(2015, 3, 1)
        )
        ChildContact.objects.create(
            organization=self.org, child=sister, parent_contact=self.parent, role="mother"
        )
        Child.objects.filter(pk=self.child.pk).update(status="left")
        kids = self.me()["children"]
        self.assertEqual(
            [(c["full_name"], c["status"]) for c in kids],
            [("Абаева Аружан", "active"), ("Касымова Айлин", "left")],
        )

    def test_child_detail_only_own(self):
        _, (stranger,) = family(self.org, "Чужая мама", "+77019990000", "Чужой Ребёнок")
        client = self.as_parent(self.login())
        self.assertEqual(
            client.get(f"/api/v1/portal/children/{self.child.id}/").data["full_name"],
            "Касымова Айлин",
        )
        self.assertEqual(client.get(f"/api/v1/portal/children/{stranger.id}/").status_code, 404)

    def test_child_card_has_no_staff_fields(self):
        Child.objects.filter(pk=self.child.pk).update(
            medical_notes="Аллергия", leave_reason="дорого"
        )
        child = self.me()["children"][0]
        self.assertNotIn("medical_notes", child)
        self.assertNotIn("leave_reason", child)

    def test_profile_email_and_language(self):
        client = self.as_parent(self.login())
        profile = client.patch(
            "/api/v1/portal/profile/", {"email": "mama@mail.kz", "language": "kk"}, format="json"
        ).data
        self.assertEqual(
            (profile["email"], profile["language"], profile["full_name"]),
            ("mama@mail.kz", "kk", "Касымова Гульмира"),
        )
        self.parent.refresh_from_db()
        self.assertEqual(self.parent.email, "mama@mail.kz")
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.Action.UPDATE, object_id=self.parent.pk
            ).exists()
        )
        self.assertEqual(
            client.patch("/api/v1/portal/profile/", {"language": "en"}, format="json").status_code,
            400,
        )

    def test_phone_change_requires_code_on_new_number(self):
        client = self.as_parent(self.login())
        new = "+77075550000"
        self.assertEqual(
            self.ask_change(client, new).status_code,
            200,
        )
        self.assertEqual(self.sent[-1][0], new)  # код ушёл на НОВЫЙ номер
        code = self.sent[-1][1]
        wrong = "000000" if code != "000000" else "111111"
        self.assertEqual(
            client.post(
                "/api/v1/portal/profile/phone/", {"phone": new, "code": wrong}, format="json"
            ).status_code,
            400,
        )
        response = client.post(
            "/api/v1/portal/profile/phone/", {"phone": new, "code": code}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["phone"], new)
        self.assertTrue(
            ContactPhone.objects.filter(parent_contact=self.parent, number=new).exists()
        )
        self.assertFalse(ContactPhone.objects.filter(number=MAMA).exists())
        # Сессия та же, дети те же — под новым номером.
        self.assertEqual(
            [c["full_name"] for c in client.get("/api/v1/portal/me/").data["children"]],
            ["Касымова Айлин"],
        )
        self.assertEqual(ParentAccount.objects.get().phone, new)

    def test_login_code_cannot_change_phone(self):
        client = self.as_parent(self.login())
        new = "+77075550000"
        self.ask_change(client, new)
        # Код для входа на новый номер не подходит для смены (и наоборот).
        OtpChallenge.objects.filter(purpose=OtpChallenge.Purpose.PHONE_CHANGE).update(
            purpose=OtpChallenge.Purpose.LOGIN
        )
        response = client.post(
            "/api/v1/portal/profile/phone/", {"phone": new, "code": self.sent[-1][1]}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_phone_already_used_for_login_is_refused(self):
        family(self.org, "Папа", PAPA, "Ахметов Тимур")
        self.login(PAPA)
        self.age_challenges(PAPA)
        client = self.as_parent(self.login(MAMA))
        response = self.ask_change(client, PAPA)
        self.assertEqual(response.status_code, 400)
        self.assertIn("администратор", response.data["detail"])

    def test_phone_change_code_expires(self):
        client = self.as_parent(self.login())
        new = "+77075550000"
        self.ask_change(client, new)
        OtpChallenge.objects.filter(phone=new).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        response = client.post(
            "/api/v1/portal/profile/phone/", {"phone": new, "code": self.sent[-1][1]}, format="json"
        )
        self.assertEqual(response.status_code, 400)
