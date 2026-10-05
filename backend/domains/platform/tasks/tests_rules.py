from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from domains.money.payments.models import Payment
from domains.money.subscriptions.debt import create_tasks_for_overdue_debt
from domains.money.subscriptions.sales import sell_subscription
from domains.money.subscriptions.statuses import suggest_renewal
from domains.money.subscriptions.subscription_types import create_type
from domains.people.clients.models import Child
from domains.platform.leads.models import Lead
from domains.platform.leads.rules import create_tasks_for_stale_leads
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.tenants.org_settings import (
    RULE_DEBT_REMINDER_ENABLED,
    RULE_LEAD_STALE_ENABLED,
)
from domains.platform.users.models import User

from .models import Task


class AutomationRuleTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.branch = Branch.objects.create(organization=self.org, name="Филиал на Абая")
        self.ballet = Direction.objects.create(organization=self.org, name="Балет")
        self.admin = User.objects.create_user(
            phone="77001112233",
            password="pass",
            full_name="Админ",
            organization=self.org,
            role=User.Role.ADMIN,
        )
        self.admin.branches.set([self.branch])

    def test_lead_stale_creates_call_back_task(self):
        lead = Lead.objects.create(
            organization=self.org,
            parent_name="Родитель",
            phone="77011112222",
            branch=self.branch,
            assigned_to=self.admin,
        )
        Lead.objects.filter(pk=lead.pk).update(
            status_changed_at=timezone.now() - timedelta(days=10)
        )
        created = create_tasks_for_stale_leads()
        self.assertEqual(created, 1)
        task = Task.objects.get(lead=lead)
        self.assertEqual(task.type, Task.Type.CALL_BACK)
        self.assertEqual(task.assigned_to, self.admin)

    def test_lead_stale_rule_disabled_creates_nothing(self):
        self.org.settings = {**self.org.settings, RULE_LEAD_STALE_ENABLED: False}
        self.org.save(update_fields=["settings"])
        lead = Lead.objects.create(
            organization=self.org,
            parent_name="Родитель",
            phone="77011112222",
            branch=self.branch,
            assigned_to=self.admin,
        )
        Lead.objects.filter(pk=lead.pk).update(
            status_changed_at=timezone.now() - timedelta(days=10)
        )
        created = create_tasks_for_stale_leads()
        self.assertEqual(created, 0)

    def test_lead_stale_rerun_does_not_duplicate(self):
        lead = Lead.objects.create(
            organization=self.org,
            parent_name="Родитель",
            phone="77011112222",
            branch=self.branch,
            assigned_to=self.admin,
        )
        Lead.objects.filter(pk=lead.pk).update(
            status_changed_at=timezone.now() - timedelta(days=10)
        )
        create_tasks_for_stale_leads()
        create_tasks_for_stale_leads()
        create_tasks_for_stale_leads()
        self.assertEqual(Task.objects.filter(lead=lead).count(), 1)

    def test_debt_reminder_creates_payment_reminder_task(self):
        child = Child.objects.create(
            organization=self.org,
            full_name="Иванов Алихан",
            birth_date=date(2018, 1, 1),
            gender=Child.Gender.MALE,
        )
        sub_type = create_type(
            self.org,
            name="8 занятий",
            price=25000,
            quota_sessions=8,
            duration_days=30,
            directions=[self.ballet],
        )
        sub, _payment = sell_subscription(
            actor=self.admin,
            child=child,
            subscription_type_version=sub_type.versions.latest(),
            direction=self.ballet,
            branch=self.branch,
            starts_on=date.today() - timedelta(days=10),
            paid_amount=10000,
            payment_method=Payment.Method.CASH,
        )
        created = create_tasks_for_overdue_debt()
        self.assertEqual(created, 1)
        task = Task.objects.get(child=child)
        self.assertEqual(task.type, Task.Type.PAYMENT_REMINDER)

    def test_debt_reminder_rerun_does_not_duplicate(self):
        child = Child.objects.create(
            organization=self.org,
            full_name="Иванов Алихан",
            birth_date=date(2018, 1, 1),
            gender=Child.Gender.MALE,
        )
        sub_type = create_type(
            self.org,
            name="8 занятий",
            price=25000,
            quota_sessions=8,
            duration_days=30,
            directions=[self.ballet],
        )
        sell_subscription(
            actor=self.admin,
            child=child,
            subscription_type_version=sub_type.versions.latest(),
            direction=self.ballet,
            branch=self.branch,
            starts_on=date.today() - timedelta(days=10),
            paid_amount=10000,
            payment_method=Payment.Method.CASH,
        )
        create_tasks_for_overdue_debt()
        create_tasks_for_overdue_debt()
        create_tasks_for_overdue_debt()
        self.assertEqual(Task.objects.filter(child=child).count(), 1)

    def test_debt_reminder_disabled_creates_nothing(self):
        self.org.settings = {**self.org.settings, RULE_DEBT_REMINDER_ENABLED: False}
        self.org.save(update_fields=["settings"])
        child = Child.objects.create(
            organization=self.org,
            full_name="Иванов Алихан",
            birth_date=date(2018, 1, 1),
            gender=Child.Gender.MALE,
        )
        sub_type = create_type(
            self.org,
            name="8 занятий",
            price=25000,
            quota_sessions=8,
            duration_days=30,
            directions=[self.ballet],
        )
        sell_subscription(
            actor=self.admin,
            child=child,
            subscription_type_version=sub_type.versions.latest(),
            direction=self.ballet,
            branch=self.branch,
            starts_on=date.today() - timedelta(days=10),
            paid_amount=10000,
            payment_method=Payment.Method.CASH,
        )
        self.assertEqual(create_tasks_for_overdue_debt(), 0)

    def test_renewal_offer_created_on_status_recalc(self):
        child = Child.objects.create(
            organization=self.org,
            full_name="Иванов Алихан",
            birth_date=date(2018, 1, 1),
            gender=Child.Gender.MALE,
        )
        sub_type = create_type(
            self.org,
            name="8 занятий",
            price=25000,
            quota_sessions=8,
            duration_days=30,
            directions=[self.ballet],
        )
        sub, _payment = sell_subscription(
            actor=self.admin,
            child=child,
            subscription_type_version=sub_type.versions.latest(),
            direction=self.ballet,
            branch=self.branch,
            starts_on=date.today() - timedelta(days=25),
            paid_amount=25000,
            payment_method=Payment.Method.CASH,
        )
        suggest_renewal(sub)
        task = Task.objects.get(child=child, type=Task.Type.RENEWAL_OFFER)
        self.assertEqual(task.source, Task.Source.AUTO)

    def test_renewal_offer_rerun_does_not_duplicate(self):
        child = Child.objects.create(
            organization=self.org,
            full_name="Иванов Алихан",
            birth_date=date(2018, 1, 1),
            gender=Child.Gender.MALE,
        )
        sub_type = create_type(
            self.org,
            name="8 занятий",
            price=25000,
            quota_sessions=8,
            duration_days=30,
            directions=[self.ballet],
        )
        sub, _payment = sell_subscription(
            actor=self.admin,
            child=child,
            subscription_type_version=sub_type.versions.latest(),
            direction=self.ballet,
            branch=self.branch,
            starts_on=date.today() - timedelta(days=25),
            paid_amount=25000,
            payment_method=Payment.Method.CASH,
        )
        suggest_renewal(sub)
        suggest_renewal(sub)
        suggest_renewal(sub)
        self.assertEqual(Task.objects.filter(child=child, type=Task.Type.RENEWAL_OFFER).count(), 1)

    def test_tenant_isolation(self):
        other_org = Organization.objects.create(name="Другой центр", slug="other")
        other_admin = User.objects.create_user(
            phone="77009990000",
            password="pass",
            full_name="Чужой админ",
            organization=other_org,
            role=User.Role.ADMIN,
        )
        lead = Lead.objects.create(
            organization=other_org,
            parent_name="Чужой родитель",
            phone="77099998888",
            assigned_to=other_admin,
        )
        Lead.objects.filter(pk=lead.pk).update(
            status_changed_at=timezone.now() - timedelta(days=10)
        )
        create_tasks_for_stale_leads()
        self.assertEqual(Task.objects.filter(organization=self.org).count(), 0)
        self.assertEqual(Task.objects.filter(organization=other_org).count(), 1)
