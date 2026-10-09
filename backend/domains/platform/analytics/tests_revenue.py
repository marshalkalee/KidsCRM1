"""Выручка по оплатам (TRU-123): критерии приёмки — отмена, разрезы, шаг графика."""

from datetime import timedelta
from decimal import Decimal

from domains.money.payments.models import Payment
from domains.money.payments.services import cancel_payment
from domains.money.subscriptions.models import Subscription

from .breakdowns import breakdown
from .epoch import epoch_of
from .period import Period, PeriodError, period_for
from .registry import compute
from .scope import Scope
from .tests import AnalyticsFixtures

DIMENSIONS = ["branch", "direction", "method", "subscription_type", "client"]


class RevenueTests(AnalyticsFixtures):
    def last_month(self):
        end = self.today.replace(day=1) - timedelta(days=1)
        return Period(end.replace(day=1), end, "custom")

    def revenue(self, period, *, use_cache=False):
        scope = Scope(self.org, None)
        return Decimal(compute(["revenue"], scope, period, use_cache=use_cache)["revenue"]["value"])

    def test_cancelled_payment_reduces_month_it_was_taken_in(self):
        """Отмена сегодня уменьшает прошлый месяц, а текущий не трогает."""
        last = self.last_month()
        kept = self.pay(self.subscription(self.abaya), 30000, day=last.start + timedelta(days=5))
        gone = self.pay(self.subscription(self.abaya), 10000, day=last.start + timedelta(days=6))
        self.pay(self.subscription(self.abaya), 20000)
        this_month = period_for("month", self.today)
        self.assertEqual(self.revenue(last), 40000)
        cancel_payment(gone, actor=self.owner, reason="Ошибка кассира")
        self.assertEqual(self.revenue(last), 30000)
        self.assertEqual(self.revenue(this_month), 20000)
        self.assertEqual(Payment.objects.filter(pk=kept.pk).count(), 1)

    def test_cancel_resets_cached_report(self):
        """Закрытый период лежит в кэше час: после отмены цифра обновляется сразу."""
        last = self.last_month()
        payment = self.pay(self.subscription(self.abaya), 30000, day=last.start + timedelta(days=3))
        self.assertEqual(self.revenue(last, use_cache=True), 30000)
        self.assertEqual(self.revenue(last, use_cache=True), 30000)  # из кэша
        cancel_payment(payment, actor=self.owner, reason="Возврат")
        self.assertEqual(self.revenue(last, use_cache=True), 0)

    def test_new_payment_does_not_reset_cache_but_cancel_does(self):
        before = epoch_of(self.org.pk)
        payment = self.pay(self.subscription(self.abaya), 1000)
        self.assertEqual(epoch_of(self.org.pk), before)
        cancel_payment(payment, actor=self.owner, reason="Ошибка")
        self.assertNotEqual(epoch_of(self.org.pk), before)

    def test_every_breakdown_adds_up_to_total(self):
        first = self.subscription(self.abaya)
        renewal = self.subscription(self.saina, child=first.child)
        Subscription.objects.filter(pk=renewal.pk).update(renewed_from=first)
        self.pay(first, 30000)
        self.pay(renewal, 15000)
        self.pay(self.subscription(self.saina), 7000)
        self.pay(self.subscription(self.abaya), 5000)
        scope, period = Scope(self.org, None), period_for("month", self.today)
        total = self.revenue(period)
        self.assertEqual(total, 57000)
        for dimension in DIMENSIONS:
            items = breakdown("revenue", dimension, scope, period)
            self.assertEqual(sum(Decimal(str(i["value"])) for i in items), total, dimension)

    def test_series_sums_to_total_at_every_step(self):
        self.pay(self.subscription(self.abaya), 1000)
        self.pay(self.subscription(self.abaya), 2000, day=self.today - timedelta(days=20))
        self.pay(self.subscription(self.abaya), 2000, day=self.today - timedelta(days=45))
        period = Period(self.today - timedelta(days=60), self.today, "custom")
        for step in ("day", "week", "month"):
            stepped = period_for("custom", self.today, period.start, period.end, step)
            data = compute(["revenue"], Scope(self.org, None), stepped, use_cache=False)["revenue"]
            self.assertEqual(sum(Decimal(p["value"]) for p in data["series"]), 5000, step)
            self.assertEqual(len(data["series"]), len(stepped.bucket_starts()), step)

    def test_month_step_on_long_period(self):
        self.pay(self.subscription(self.abaya), 1000, day=self.today - timedelta(days=40))
        self.pay(self.subscription(self.abaya), 2000)
        period = period_for(
            "custom", self.today, self.today - timedelta(days=60), self.today, "month"
        )
        self.assertEqual(period.granularity, "month")
        self.assertEqual(period.previous().granularity, "month")
        data = compute(["revenue"], Scope(self.org, None), period, use_cache=False)["revenue"]
        self.assertTrue(all(p["date"].endswith("-01") for p in data["series"]))

    def test_unknown_step_is_rejected(self):
        with self.assertRaises(PeriodError):
            period_for("month", self.today, step="hour")

    def test_api_granularity_param(self):
        self.pay(self.subscription(self.abaya), 1000)
        self.client.force_authenticate(self.owner)
        data = self.client.get(
            "/api/v1/analytics/metrics/",
            {"metrics": "revenue", "period": "month", "granularity": "week"},
        ).data
        self.assertEqual(data["period"]["granularity"], "week")
        bad = self.client.get(
            "/api/v1/analytics/metrics/", {"metrics": "revenue", "granularity": "hour"}
        )
        self.assertEqual(bad.status_code, 400)
