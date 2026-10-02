from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest import mock

import pytz
from django.test import SimpleTestCase, tag
from rest_framework.test import APITestCase

from domains.money.payments.models import Payment
from domains.money.payments.services import record_payment
from domains.money.subscriptions.models import Subscription
from domains.money.subscriptions.subscription_types import create_type
from domains.people.clients.models import Child
from domains.platform.core.utils import today_for_org
from domains.platform.leads.models import Lead, LeadKind
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.platform.users.models import User
from domains.scheduling.attendance.models import Attendance
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.schedule.models import Lesson

from . import metrics  # noqa: F401
from .models import MetricSnapshot
from .period import Period, PeriodError, period_for
from .registry import compute
from .scope import Scope
from .snapshots import snapshot_organization

URL = "/api/v1/analytics/metrics/"


class PeriodTests(SimpleTestCase):
    today = date(2026, 9, 15)

    def test_presets_run_up_to_today(self):
        self.assertEqual(
            period_for("month", self.today), Period(date(2026, 9, 1), self.today, "month")
        )
        self.assertEqual(period_for("week", self.today).start, date(2026, 9, 14))
        self.assertEqual(period_for("quarter", self.today).start, date(2026, 7, 1))
        self.assertEqual(period_for("year", self.today).start, date(2026, 1, 1))

    def test_previous_month_is_same_part_of_month(self):
        """1–15 сентября сравниваем с 1–15 августа, не с целым августом."""
        previous = period_for("month", self.today).previous()
        self.assertEqual((previous.start, previous.end), (date(2026, 8, 1), date(2026, 8, 15)))
        march = Period(date(2026, 3, 1), date(2026, 3, 31), "month").previous()
        self.assertEqual((march.start, march.end), (date(2026, 2, 1), date(2026, 2, 28)))

    def test_custom_period_checks(self):
        with self.assertRaises(PeriodError):
            period_for("custom", self.today, date(2026, 9, 10), date(2026, 9, 1))
        with self.assertRaises(PeriodError):
            period_for("custom", self.today, date(2024, 1, 1), date(2026, 1, 1))
        future = period_for("custom", self.today, date(2026, 9, 1), date(2026, 12, 31))
        self.assertEqual(future.end, self.today)
        previous = Period(date(2026, 9, 1), date(2026, 9, 10)).previous()
        self.assertEqual((previous.start, previous.end), (date(2026, 8, 22), date(2026, 8, 31)))

    def test_granularity_and_buckets(self):
        self.assertEqual(Period(date(2026, 9, 1), date(2026, 9, 30)).granularity, "day")
        quarter = Period(date(2026, 7, 1), date(2026, 9, 30))
        self.assertEqual(quarter.granularity, "week")
        self.assertEqual(quarter.bucket_starts()[0], date(2026, 6, 29))  # понедельник
        year = Period(date(2025, 10, 1), date(2026, 9, 30))
        self.assertEqual(len(year.bucket_starts()), 12)


class AnalyticsFixtures(APITestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="tb-analytics")
        self.abaya = Branch.objects.create(organization=self.org, name="Абая")
        self.saina = Branch.objects.create(organization=self.org, name="Саина")
        self.ballet = Direction.objects.create(organization=self.org, name="Балет")
        self.type = create_type(
            self.org, name="8 занятий", price=30000, quota_sessions=8, duration_days=30
        )
        self.owner = self.user("+77010000001", User.Role.OWNER)
        self.today = today_for_org(self.org)
        self.tz = pytz.timezone(self.org.timezone)

    def user(self, phone, role, branches=()):
        user = User.objects.create_user(
            phone=phone, password="x", full_name=phone, organization=self.org, role=role
        )
        user.branches.set(branches)
        return user

    def child(self, name="Алия"):
        return Child.objects.create(
            organization=self.org, full_name=name, birth_date=date(2018, 1, 1), gender="female"
        )

    def subscription(self, branch, child=None, price=30000):
        return Subscription.objects.create(
            organization=self.org,
            child=child or self.child(),
            subscription_type_version=self.type.versions.latest(),
            direction=self.ballet,
            branch=branch,
            starts_on=self.today,
            ends_on=self.today + timedelta(days=30),
            list_price=price,
            price=price,
        )

    def pay(self, subscription, amount, day=None, hour=12):
        payment = record_payment(
            actor=self.owner, subscription=subscription, amount=amount, method="cash"
        )
        day = day or self.today
        Payment.objects.filter(pk=payment.pk).update(
            paid_at=self.tz.localize(datetime.combine(day, time(hour)))
        )
        return payment

    def metric(self, name, scope=None, period=None, **kwargs):
        return compute(
            [name],
            scope or Scope(self.org, None),
            period or period_for("month", self.today),
            use_cache=False,
            **kwargs,
        )[name]


class MetricTests(AnalyticsFixtures):
    def test_revenue_counts_only_confirmed_and_splits_by_branch(self):
        self.pay(self.subscription(self.abaya), 30000)
        self.pay(self.subscription(self.saina), 15000)
        cancelled = self.pay(self.subscription(self.saina), 7000)
        cancelled.delete()
        Payment.objects.filter(pk=self.pay(self.subscription(self.abaya), 5000).pk).update(
            status=Payment.Status.PENDING
        )
        self.assertEqual(self.metric("revenue")["value"], "45000")
        self.assertEqual(
            self.metric("revenue", Scope(self.org, (self.abaya.pk,)))["value"], "30000"
        )
        self.assertEqual(self.metric("payments_count")["value"], 2)
        self.assertEqual(self.metric("average_check")["value"], "22500")

    def test_day_boundary_is_center_time(self):
        """Оплата в 23:30 по Алматы — это ещё тот день, хотя в UTC уже другой."""
        yesterday = self.today - timedelta(days=1)
        self.pay(self.subscription(self.abaya), 10000, day=yesterday, hour=23)
        today_only = Period(self.today, self.today)
        self.assertEqual(self.metric("revenue", period=today_only)["value"], 0)
        self.assertEqual(
            self.metric("revenue", period=Period(yesterday, yesterday))["value"], "10000"
        )

    def test_series_adds_up_and_compares_with_previous_period(self):
        month = period_for("month", self.today)
        self.pay(self.subscription(self.abaya), 30000, day=month.start)
        self.pay(self.subscription(self.abaya), 10000, day=month.end)
        previous = month.previous()
        self.pay(self.subscription(self.abaya), 20000, day=previous.start)
        result = self.metric("revenue", period=month)
        self.assertEqual(sum(Decimal(str(p["value"])) for p in result["series"]), Decimal(40000))
        self.assertEqual(len(result["series"]), month.days)
        self.assertEqual((result["previous"], result["change_percent"]), ("20000", "100"))

    def test_debt_is_the_same_as_debtors_screen(self):
        self.pay(self.subscription(self.abaya), 10000)
        overpaid = self.subscription(self.saina)
        self.pay(overpaid, 35000)
        self.subscription(self.saina, price=12000)
        self.client.force_authenticate(self.owner)
        screen = self.client.get("/api/v1/subscriptions/debtors/").data["total_debt"]
        self.assertEqual(Decimal(screen), Decimal(32000))
        self.assertEqual(self.metric("debt_total")["value"], "32000")
        self.assertEqual(
            self.metric("debt_total", Scope(self.org, (self.saina.pk,)))["value"], "12000"
        )

    def test_attendance_metrics(self):
        group = Group.objects.create(
            organization=self.org, branch=self.abaya, direction=self.ballet, name="Г1", capacity=4
        )
        kids = [self.child(f"Ребёнок {i}") for i in range(3)]
        for kid in kids:
            GroupMembership.objects.create(
                organization=self.org, group=group, child=kid, joined_at=self.today
            )
        start = self.tz.localize(datetime.combine(self.today, time(10)))
        lesson = Lesson.objects.create(
            organization=self.org, group=group, starts_at=start, ends_at=start + timedelta(hours=1)
        )
        for kid, status in zip(kids, ["present", "makeup", "absent"], strict=True):
            Attendance.objects.create(
                organization=self.org, lesson=lesson, child=kid, status=status
            )
        self.assertEqual(self.metric("visits")["value"], 2)
        self.assertEqual(self.metric("attendance_rate")["value"], "66.7")
        self.assertEqual(self.metric("active_children")["value"], 2)
        self.assertEqual(self.metric("group_fill")["value"], "75")
        self.assertEqual(self.metric("visits", Scope(self.org, (self.saina.pk,)))["value"], 0)

    def test_new_leads_without_renewals(self):
        Lead.objects.create(organization=self.org, parent_name="А", phone="+77011111111")
        Lead.objects.create(
            organization=self.org, parent_name="Б", phone="+77012222222", kind=LeadKind.RENEWAL
        )
        self.assertEqual(self.metric("new_leads")["value"], 1)

    def test_little_history_is_flagged(self):
        self.pay(self.subscription(self.abaya), 30000)
        result = self.metric("revenue")
        self.assertFalse(result["enough_data"])
        self.assertEqual(result["days_until_enough"], 27)
        empty = self.metric("visits")
        self.assertEqual((empty["enough_data"], empty["data_since"]), (False, None))
        self.assertTrue(self.metric("debt_total")["enough_data"])


class SnapshotTests(AnalyticsFixtures):
    def test_snapshot_once_a_day_and_used_as_history(self):
        sub = self.subscription(self.abaya)
        self.assertEqual(snapshot_organization(self.org), 6)  # 2 метрики × (орг + 2 филиала)
        self.pay(sub, 10000)
        snapshot_organization(self.org)
        rows = MetricSnapshot.objects.filter(metric="debt_total", branch__isnull=True)
        self.assertEqual([r.value for r in rows], [Decimal(20000)])
        MetricSnapshot.objects.create(
            organization=self.org,
            metric="debt_total",
            date=period_for("month", self.today).previous().end,
            value=Decimal(40000),
        )
        result = self.metric("debt_total")
        self.assertEqual(result["series"], [{"date": self.today.isoformat(), "value": "20000"}])
        self.assertEqual((result["previous"], result["change_percent"]), ("40000", "-50"))
        two_branches = self.metric("debt_total", Scope(self.org, (self.abaya.pk, self.saina.pk)))
        self.assertIsNone(two_branches["series"])


class ApiTests(AnalyticsFixtures):
    def setUp(self):
        super().setUp()
        self.pay(self.subscription(self.abaya), 30000)
        self.pay(self.subscription(self.saina), 15000)

    def get(self, user, **params):
        self.client.force_authenticate(user)
        return self.client.get(URL, {"metrics": "revenue", **params})

    def test_owner_sees_all_or_chosen_branches(self):
        data = self.get(self.owner).data
        self.assertTrue(data["all_branches"])
        self.assertEqual(data["metrics"]["revenue"]["value"], "45000")
        self.assertEqual(data["period"]["preset"], "month")
        self.client.force_authenticate(self.owner)
        both = self.client.get(
            URL, {"metrics": "revenue", "branch": [str(self.abaya.pk), str(self.saina.pk)]}
        ).data
        self.assertEqual(both["metrics"]["revenue"]["value"], "45000")
        self.assertEqual([b["name"] for b in both["branches"]], ["Абая", "Саина"])

    def test_manager_sees_only_own_branches(self):
        manager = self.user("+77010000002", User.Role.MANAGER, [self.abaya])
        own = self.get(manager).data
        self.assertEqual(own["metrics"]["revenue"]["value"], "30000")
        self.assertFalse(own["all_branches"])
        self.assertEqual([b["name"] for b in own["branches"]], ["Абая"])
        self.assertEqual(self.get(manager, branch=str(self.saina.pk)).status_code, 403)
        self.client.force_authenticate(manager)
        catalog = self.client.get("/api/v1/analytics/catalog/").data
        self.assertEqual([b["name"] for b in catalog["branches"]], ["Абая"])
        self.assertFalse(catalog["can_see_all_branches"])

    def test_header_branch_is_used(self):
        self.client.force_authenticate(self.owner)
        data = self.client.get(
            URL, {"metrics": "revenue"}, HTTP_X_BRANCH_ID=str(self.saina.pk)
        ).data
        self.assertEqual(data["metrics"]["revenue"]["value"], "15000")

    def test_admin_and_teacher_have_no_access(self):
        for role in (User.Role.ADMIN, User.Role.TEACHER, User.Role.ACCOUNTANT):
            user = self.user(f"+7701000009{list(User.Role).index(role)}", role)
            self.assertEqual(self.get(user).status_code, 403, role)

    def test_bad_requests(self):
        self.assertEqual(self.get(self.owner, metrics="nope").status_code, 400)
        bad_period = self.get(self.owner, period="custom", **{"from": "2026-01-01"})
        self.assertEqual(bad_period.status_code, 400)
        self.assertIn("period", bad_period.data)

    def test_breakdown_by_method_and_branch(self):
        self.client.force_authenticate(self.owner)
        by_method = self.client.get(
            "/api/v1/analytics/breakdown/", {"metric": "revenue", "by": "method"}
        ).data
        self.assertEqual(by_method["unit"], "money")
        self.assertEqual(
            [(i["key"], i["label"], i["value"]) for i in by_method["items"]],
            [("cash", "Наличные", "45000")],
        )
        by_branch = self.client.get(
            "/api/v1/analytics/breakdown/", {"metric": "revenue", "by": "branch"}
        ).data["items"]
        self.assertEqual(
            [(i["label"], i["value"]) for i in by_branch], [("Абая", "30000"), ("Саина", "15000")]
        )
        bad = self.client.get("/api/v1/analytics/breakdown/", {"metric": "revenue", "by": "hour"})
        self.assertEqual(bad.status_code, 400)

    def test_revenue_new_clients_and_renewals(self):
        first = self.subscription(self.abaya)
        renewal = self.subscription(self.abaya, child=first.child)
        Subscription.objects.filter(pk=renewal.pk).update(renewed_from=first)
        self.pay(renewal, 30000)
        self.client.force_authenticate(self.owner)
        items = self.client.get(
            "/api/v1/analytics/breakdown/", {"metric": "revenue", "by": "client"}
        ).data["items"]
        self.assertEqual(
            {i["key"]: i["value"] for i in items}, {"new": "45000", "renewal": "30000"}
        )

    def test_absence_reasons_and_teachers(self):
        teacher = self.user("+77010000005", User.Role.TEACHER)
        group = Group.objects.create(
            organization=self.org, branch=self.abaya, direction=self.ballet, name="Г", capacity=5
        )
        start = self.tz.localize(datetime.combine(self.today, time(10)))
        lesson = Lesson.objects.create(
            organization=self.org,
            group=group,
            teacher=teacher,
            starts_at=start,
            ends_at=start + timedelta(hours=1),
        )
        for reason in ["illness", "illness", ""]:
            Attendance.objects.create(
                organization=self.org,
                lesson=lesson,
                child=self.child(),
                status="absent",
                absence_reason=reason,
            )
        self.client.force_authenticate(self.owner)
        get = lambda metric, by: self.client.get(  # noqa: E731
            "/api/v1/analytics/breakdown/", {"metric": metric, "by": by}
        ).data["items"]
        self.assertEqual(
            [(i["key"], i["label"], i["value"]) for i in get("absences", "reason")],
            [("illness", "Болезнь", 2), (None, None, 1)],
        )
        self.assertEqual(
            [(i["label"], i["value"]) for i in get("attendance_marks", "teacher")],
            [("+77010000005", 3)],
        )

    def test_manager_breakdown_only_own_branch(self):
        manager = self.user("+77010000002", User.Role.MANAGER, [self.abaya])
        self.client.force_authenticate(manager)
        items = self.client.get(
            "/api/v1/analytics/breakdown/", {"metric": "revenue", "by": "branch"}
        ).data["items"]
        self.assertEqual([i["label"] for i in items], ["Абая"])

    def test_heatmap_uses_center_time(self):
        group = Group.objects.create(
            organization=self.org, branch=self.abaya, direction=self.ballet, name="Г", capacity=5
        )
        kid = self.child()
        monday = self.today - timedelta(days=self.today.weekday())
        start = self.tz.localize(datetime.combine(monday, time(17)))
        lesson = Lesson.objects.create(
            organization=self.org, group=group, starts_at=start, ends_at=start + timedelta(hours=1)
        )
        Attendance.objects.create(organization=self.org, lesson=lesson, child=kid, status="present")
        self.client.force_authenticate(self.owner)
        cells = self.client.get(
            "/api/v1/analytics/heatmap/",
            {"period": "custom", "from": monday.isoformat(), "to": self.today.isoformat()},
        ).data["cells"]
        self.assertEqual(cells, [{"weekday": 1, "hour": 17, "value": 1}])

    def test_previous_series_for_overlay(self):
        data = self.get(self.owner).data["metrics"]["revenue"]
        self.assertEqual(len(data["previous_series"]), len(data["series"]))

    def test_works_without_redis(self):
        from . import registry

        with mock.patch.object(registry, "caches") as broken:
            broken.__getitem__.return_value.get.side_effect = ConnectionError
            broken.__getitem__.return_value.set.side_effect = ConnectionError
            self.assertEqual(self.get(self.owner).data["metrics"]["revenue"]["value"], "45000")

    @tag("tenant_isolation")
    def test_other_organization_is_invisible(self):
        other = Organization.objects.create(name="Чужой", slug="other-analytics")
        stranger = User.objects.create_user(
            phone="+77019999999",
            password="x",
            full_name="Ч",
            organization=other,
            role=User.Role.OWNER,
        )
        self.assertEqual(self.get(stranger).data["metrics"]["revenue"]["value"], 0)
