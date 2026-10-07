"""Метрики пилота «после» (TRU-152): те же цифры, что в отчётах."""

import datetime
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from domains.money.subscriptions.sales import sell_subscription
from domains.money.subscriptions.subscription_types import create_type
from domains.people.clients.models import Child
from domains.platform.leads.models import Lead
from domains.platform.leads.services import change_status, create_lead
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User

from .management.commands.pilot_metrics import pilot_metrics


class PilotMetricsTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Пилот", slug="pilot")
        self.owner = User.objects.create_user(
            phone="77010000001", password="p", full_name="Владелец", organization=self.org,
            role=User.Role.OWNER,
        )  # fmt: skip
        for i in range(4):
            lead = create_lead(
                organization=self.org, actor=self.owner, kind=Lead.Kind.NEW,
                parent_name=f"Родитель {i}", phone=f"+7701000010{i}",
            )  # fmt: skip
            if i < 1:
                change_status(lead, to_status=Lead.Status.CONTACTED, actor=self.owner)
                change_status(lead, to_status=Lead.Status.TRIAL_SCHEDULED, actor=self.owner)
        branch = Branch.objects.create(organization=self.org, name="Центр")
        direction = Direction.objects.create(organization=self.org, name="Балет")
        version = create_type(
            self.org, name="8", price=25000, quota_sessions=8, duration_days=30
        ).versions.latest()
        child = Child.objects.create(
            organization=self.org, full_name="Алия", birth_date=datetime.date(2018, 1, 1)
        )
        sell_subscription(
            actor=self.owner, child=child, subscription_type_version=version, direction=direction,
            branch=branch, starts_on=timezone.localdate(), paid_amount=10000, payment_method="cash",
        )  # fmt: skip

    def test_conversion_and_debts(self):
        today = timezone.localdate()
        m = pilot_metrics(self.org, today - datetime.timedelta(days=1), today)
        self.assertEqual((m["leads"], m["trials"], m["lead_to_trial_percent"]), (4, 1, 25.0))
        self.assertEqual((m["debt_children"], m["debt_total"]), (1, 15000))

    def test_command_prints_table_rows(self):
        out = StringIO()
        today = timezone.localdate().isoformat()
        call_command("pilot_metrics", org="pilot", start=today, end=today, stdout=out)
        self.assertIn("| Конверсия заявок в пробное | 25.0 % (1 из 4 заявок) |", out.getvalue())
        self.assertIn("сумма: 15 000 ₸", out.getvalue())
