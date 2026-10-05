"""TRU-158: слой агрегатов для ИИ не выдаёт людей. Блокирующий тест —
метка tenant_isolation, как у кабинета родителя (portal/tests_isolation.py)."""

import datetime
import inspect
import json
import re

from django.test import TestCase, tag

from domains.money.subscriptions.sales import sell_subscription
from domains.money.subscriptions.subscription_types import create_type
from domains.people.clients.models import Child, ChildContact, ContactPhone, ParentContact
from domains.platform.analytics.group_occupancy import group_occupancy
from domains.platform.analytics.period import period_for
from domains.platform.analytics.registry import compute
from domains.platform.analytics.scope import Scope
from domains.platform.core.utils import today_for_org
from domains.platform.leads.models import LeadRejectionReason, LeadSource
from domains.platform.leads.services import change_status, create_lead
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group, GroupMembership

from . import aggregates

MARKERS = (
    "Бекова",
    "Алтынай",
    "Нурланова",
    "Гаухар",
    "Сапарова",
    "Меруерт",
    "7071112233",
    "example.kz",
    "2019-03-01",
    "01.03.2019",
    "Жумабекова",
)
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


@tag("tenant_isolation")
class AggregatesTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="tb")
        self.owner = User.objects.create_user(
            phone="77010000001",
            password="x",
            full_name="Жумабекова Сауле",
            organization=self.org,
            role=User.Role.OWNER,
        )
        branch = Branch.objects.create(organization=self.org, name="Центр")
        ballet = Direction.objects.create(organization=self.org, name="Балет")
        version = create_type(
            self.org,
            name="8 занятий",
            price=25000,
            quota_sessions=8,
            duration_days=30,
            directions=[ballet],
        ).versions.latest()
        # Индивидуальная «группа» с именем ребёнка в названии — имя уйдёт меткой.
        self.personal = Group.objects.create(
            organization=self.org,
            branch=branch,
            direction=ballet,
            name="Индивидуально Бекова Алтынай",
            capacity=1,
        )
        self.group = Group.objects.create(
            organization=self.org, branch=branch, direction=ballet, name="Балет 5–7", capacity=12
        )
        child = Child.objects.create(
            organization=self.org, full_name="Бекова Алтынай", birth_date=datetime.date(2019, 3, 1)
        )
        parent = ParentContact.objects.create(
            organization=self.org,
            full_name="Нурланова Гаухар",
            whatsapp="+77071112233",
            email="mama@example.kz",
        )
        ContactPhone.objects.create(
            organization=self.org, parent_contact=parent, number="+77071112233"
        )
        ChildContact.objects.create(
            organization=self.org, child=child, parent_contact=parent, is_payer=True
        )
        GroupMembership.objects.create(
            organization=self.org, group=self.personal, child=child, joined_at=datetime.date.today()
        )
        sell_subscription(
            actor=self.owner,
            child=child,
            subscription_type_version=version,
            direction=ballet,
            branch=branch,
            starts_on=datetime.date.today(),
            paid_amount=10000,
            payment_method="cash",
        )
        lead = create_lead(
            organization=self.org,
            actor=self.owner,
            parent_name="Сапарова Меруерт",
            phone="+77015554433",
            source=LeadSource.objects.get(organization=self.org, name="Instagram"),
        )
        change_status(
            lead,
            to_status="rejected",
            actor=self.owner,
            rejection_reason=LeadRejectionReason.objects.get(
                organization=self.org, name="Дорого", kind="new"
            ),
            comment="Сапарова Меруерт сказала, что дорого, звонить 8 701 555 44 33",
        )
        self.scope = Scope(self.org, None, [])
        self.period = period_for("month", today_for_org(self.org))

    def test_no_people_and_no_ids_in_any_aggregate(self):
        out = json.dumps(aggregates.snapshot(self.org), ensure_ascii=False, default=str)
        for marker in MARKERS:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, out)
        self.assertIsNone(UUID.search(out), out)
        self.assertNotIn("5554433", out)

    def test_every_public_function_is_registered(self):
        """Новая функция слоя без записи в AGGREGATES роняет сборку."""
        public = {
            name
            for name, obj in inspect.getmembers(aggregates, inspect.isfunction)
            if obj.__module__ == aggregates.__name__
            and not name.startswith("_")
            and name != "snapshot"
        }
        self.assertEqual(public, set(aggregates.AGGREGATES))

    def test_numbers_match_dashboard(self):
        snap = aggregates.snapshot(self.org)
        occupancy = group_occupancy(self.scope, self.period)["summary"]
        self.assertEqual(snap["occupancy"]["итого"], occupancy)
        self.assertEqual(snap["ages"]["5–6"] + snap["ages"]["7–9"], 1)
        season = snap["seasonality"]["Новых заявок"]
        self.assertEqual(len(season), 13)
        self.assertEqual(
            season[-1]["значение"],
            compute(["new_leads"], self.scope, self.period)["new_leads"]["value"],
        )
        self.assertEqual(snap["rejection_reasons"]["причины"], {"Дорого": 1})

    def test_small_samples_hide_money(self):
        snap = aggregates.snapshot(self.org)
        # Один активный ребёнок — сумм по центру нет; одна заявка — денег по источнику нет.
        self.assertIsNone(snap["money"])
        instagram = next(row for row in snap["sources"] if row["источник"] == "Instagram")
        self.assertNotIn("выручка", instagram)
        for i in range(aggregates.MIN_GROUP):
            Child.objects.create(
                organization=self.org,
                full_name=f"Ребёнок {i}",
                birth_date=datetime.date(2018, 1, 1),
            )
        self.assertIsNotNone(aggregates.snapshot(self.org)["money"])

    def test_other_organization_is_not_mixed_in(self):
        other = Organization.objects.create(name="Другой", slug="other")
        snap = aggregates.snapshot(other)
        self.assertEqual(snap["occupancy"]["итого"]["groups_count"], 0)
        self.assertEqual(sum(snap["ages"].values()), 0)
        self.assertEqual(snap["conversion"]["этот_месяц"]["заявок"], 0)
