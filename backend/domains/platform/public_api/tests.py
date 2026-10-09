"""Публичное API v1 (TRU-176): ключи, тариф, область, филиалы, лимиты,
журнал, схема и изоляция тенантов."""

import datetime
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, tag
from django.utils import timezone
from rest_framework.test import APIClient

from domains.money.subscriptions.sales import sell_subscription
from domains.money.subscriptions.subscription_types import create_type
from domains.people.clients.models import Child
from domains.platform.core.audit import AuditLog
from domains.platform.leads.models import Lead
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User
from domains.scheduling.attendance.models import Attendance
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.schedule.models import Lesson

from .auth import PerMinuteThrottle, issue_key
from .models import ApiKey, ApiRequestLog
from .urls import data_patterns

BASE = "/api/public/v1/"
TODAY = timezone.localdate()
PERIOD = (
    f"date_from={TODAY - datetime.timedelta(days=1)}&date_to={TODAY + datetime.timedelta(days=1)}"
)


def build_center(slug, phone, plan="enterprise"):
    """Центр с двумя филиалами, группой в каждом, ребёнком в каждой группе,
    занятием, отметкой, абонементом и оплатой."""
    org = Organization.objects.create(name=f"Центр {slug}", slug=slug, plan=plan)
    owner = User.objects.create_user(
        phone=phone, password="p", full_name="Владелец", organization=org, role=User.Role.OWNER
    )
    direction = Direction.objects.create(organization=org, name="Балет")
    version = create_type(
        org, name="8 занятий", price=25000, quota_sessions=8, duration_days=30,
        directions=[direction],
    ).versions.latest()  # fmt: skip
    center = {"org": org, "owner": owner, "branches": [], "children": [], "groups": []}
    for index in (1, 2):
        branch = Branch.objects.create(organization=org, name=f"Филиал {slug}-{index}")
        group = Group.objects.create(
            organization=org, branch=branch, direction=direction, name=f"Группа {slug}-{index}",
            capacity=12,
        )  # fmt: skip
        child = Child.objects.create(
            organization=org,
            full_name=f"Ребёнок {slug}-{index}",
            birth_date=datetime.date(2018, 1, 1),
        )
        GroupMembership.objects.create(organization=org, group=group, child=child, joined_at=TODAY)
        start = timezone.now()
        lesson = Lesson.objects.create(
            organization=org, group=group, teacher=owner, starts_at=start,
            ends_at=start + datetime.timedelta(hours=1),
        )  # fmt: skip
        Attendance.objects.create(
            organization=org, lesson=lesson, child=child, status=Attendance.Status.values[0]
        )
        sell_subscription(
            actor=owner, child=child, subscription_type_version=version, direction=direction,
            branch=branch, starts_on=TODAY, paid_amount=10000, payment_method="cash",
        )  # fmt: skip
        center["branches"].append(branch)
        center["children"].append(child)
        center["groups"].append(group)
    return center


def client_for(raw):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return client


# Маршрут → как проверить изоляцию: list — в ответе только свои строки;
# write — чужой филиал не принимается.
ISOLATION = {
    "children": ("list", ""),
    "groups": ("list", ""),
    "lessons": ("list", PERIOD),
    "attendance": ("list", PERIOD),
    "subscriptions": ("list", ""),
    "payments": ("list", PERIOD),
    "leads": ("write", ""),
}


class PublicApiFixtures(TestCase):
    def setUp(self):
        cache.clear()
        self.a = build_center("a", "77010000001")
        self.b = build_center("b", "77010000002")
        self.key, self.raw = issue_key(
            self.a["org"], name="1С", scope=ApiKey.Scope.READ_WRITE, branches=[],
            user=self.a["owner"],
        )  # fmt: skip
        self.api = client_for(self.raw)

    def ids(self, route, query="", client=None):
        response = (client or self.api).get(f"{BASE}{route}/?{query}")
        self.assertEqual(response.status_code, 200, response.data)
        return {row["id"] for row in response.data["results"]}


@tag("tenant_isolation")
class PublicApiIsolationTests(PublicApiFixtures):
    def foreign_ids(self, route):
        other_key, other_raw = issue_key(
            self.b["org"], name="B", scope="read", branches=[], user=self.b["owner"]
        )
        query = ISOLATION[route][1]
        return self.ids(route, query, client_for(other_raw))

    def test_every_public_route_is_covered(self):
        names = {p.name for p in data_patterns}
        self.assertEqual(
            sorted(names - set(ISOLATION)), [], "Новый публичный маршрут — добавьте в ISOLATION"
        )

    def test_key_never_sees_another_center(self):
        for route, (kind, query) in ISOLATION.items():
            if kind != "list":
                continue
            with self.subTest(route=route):
                mine, theirs = self.ids(route, query), self.foreign_ids(route)
                self.assertTrue(mine, f"{route}: свои строки должны быть")
                self.assertTrue(theirs)
                self.assertFalse(mine & theirs)

    def test_foreign_ids_in_filters_give_nothing(self):
        foreign_child = self.b["children"][0].id
        self.assertEqual(self.ids("subscriptions", f"child={foreign_child}"), set())
        self.assertEqual(self.ids("attendance", f"{PERIOD}&child={foreign_child}"), set())
        self.assertEqual(self.ids("lessons", f"{PERIOD}&group={self.b['groups'][0].id}"), set())

    def test_lead_into_foreign_branch_is_refused(self):
        response = self.api.post(
            f"{BASE}leads/",
            {
                "parent_name": "Айгерим",
                "phone": "87071112233",
                "branch_id": str(self.b["branches"][0].id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Lead.objects.filter(organization=self.b["org"]).exists())


class PublicApiAccessTests(PublicApiFixtures):
    def test_no_enterprise_plan_no_api(self):
        self.a["org"].plan = ""
        self.a["org"].save(update_fields=["plan"])
        response = self.api.get(f"{BASE}groups/")
        self.assertEqual(response.status_code, 403)
        self.assertIn("Enterprise", response.data["detail"])

    def test_missing_wrong_and_revoked_keys(self):
        self.assertEqual(APIClient().get(f"{BASE}groups/").status_code, 401)
        self.assertEqual(client_for("kc_live_nope").get(f"{BASE}groups/").status_code, 401)
        self.key.revoked_at = timezone.now()
        self.key.save()
        self.assertEqual(self.api.get(f"{BASE}groups/").status_code, 401)

    def test_staff_jwt_is_not_a_key(self):
        client = APIClient()
        client.force_authenticate(self.a["owner"])
        self.assertIn(client.get(f"{BASE}groups/").status_code, (401, 403))

    def test_read_key_cannot_write(self):
        _, raw = issue_key(self.a["org"], name="Сайт", scope="read", branches=[], user=None)
        response = client_for(raw).post(
            f"{BASE}leads/", {"parent_name": "Айгерим", "phone": "87071112233"}, format="json"
        )
        self.assertEqual(response.status_code, 403)

    def test_write_key_creates_lead(self):
        response = self.api.post(
            f"{BASE}leads/",
            {"parent_name": "Айгерим", "phone": "87071112233", "child_name": "Алия", "child_age": 6,
             "comment": "С сайта партнёра"},
            format="json",
        )  # fmt: skip
        self.assertEqual(response.status_code, 201, response.data)
        lead = Lead.objects.get(pk=response.data["id"])
        self.assertEqual((lead.organization, lead.status), (self.a["org"], "new"))
        self.assertEqual(lead.source.name, "Интеграция (API)")

    def test_branch_limited_key(self):
        first, second = self.a["branches"]
        _, raw = issue_key(
            self.a["org"], name="Филиал 1", scope="read", branches=[first], user=None
        )
        client = client_for(raw)
        self.assertEqual(self.ids("groups", client=client), {str(self.a["groups"][0].id)})
        self.assertEqual(self.ids("children", client=client), {str(self.a["children"][0].id)})
        self.assertEqual(len(self.ids("lessons", PERIOD, client)), 1)
        self.assertEqual(len(self.ids("payments", PERIOD, client)), 1)
        response = client.get(f"{BASE}subscriptions/")
        self.assertEqual({r["branch_id"] for r in response.json()["results"]}, {str(first.id)})

    def test_period_is_required_and_bounded(self):
        self.assertEqual(self.api.get(f"{BASE}lessons/").status_code, 400)
        long = f"date_from={TODAY}&date_to={TODAY + datetime.timedelta(days=90)}"
        self.assertEqual(self.api.get(f"{BASE}lessons/?{long}").status_code, 400)

    def test_rate_limit_answers_429_with_retry_after(self):
        with mock.patch.object(PerMinuteThrottle, "THROTTLE_RATES", {"public_api_minute": "2/min"}):
            codes = [self.api.get(f"{BASE}groups/").status_code for _ in range(3)]
            response = self.api.get(f"{BASE}groups/")
        self.assertEqual(codes, [200, 200, 429])
        self.assertIn("Retry-After", response)

    def test_requests_are_logged_and_last_used(self):
        self.api.get(f"{BASE}groups/")
        row = ApiRequestLog.objects.get()
        self.assertEqual((row.key, row.method, row.status), (self.key, "GET", 200))
        self.key.refresh_from_db()
        self.assertIsNotNone(self.key.last_used_at)

    def test_response_has_no_parent_contacts_or_medical_notes(self):
        response = self.api.get(f"{BASE}children/")
        self.assertEqual(
            set(response.data["results"][0]),
            {"id", "full_name", "birth_date", "status", "group_ids"},
        )

    def test_openapi_schema_is_generated_from_code(self):
        response = APIClient().get(f"{BASE}schema/?format=json")
        self.assertEqual(response.status_code, 200)
        paths = set(response.json()["paths"])
        expected = {f"{BASE}{p.pattern}" for p in data_patterns}
        self.assertEqual(paths, expected)


class ApiKeysStaffTests(PublicApiFixtures):
    def staff(self, role=User.Role.OWNER):
        user = self.a["owner"] if role == User.Role.OWNER else User.objects.create_user(
            phone="77010000099", password="p", full_name="Админ", organization=self.a["org"],
            role=role,
        )  # fmt: skip
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_owner_issues_key_shown_once_and_revokes(self):
        client = self.staff()
        created = client.post(
            "/api/v1/api-keys/",
            {"name": "Сайт", "scope": "read", "branches": [str(self.a["branches"][0].id)]},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertTrue(created.data["key"].startswith("kc_live_"))
        listing = client.get("/api/v1/api-keys/").data
        self.assertTrue(listing["enabled"])
        self.assertNotIn("key", listing["keys"][0])
        self.assertEqual(client_for(created.data["key"]).get(f"{BASE}groups/").status_code, 200)
        client.post(f"/api/v1/api-keys/{created.data['id']}/revoke/")
        self.assertEqual(client_for(created.data["key"]).get(f"{BASE}groups/").status_code, 401)
        self.assertEqual(AuditLog.objects.filter(action__in=["grant", "revoke"]).count(), 2)

    def test_admin_cannot_manage_keys(self):
        self.assertEqual(self.staff(User.Role.ADMIN).get("/api/v1/api-keys/").status_code, 403)
