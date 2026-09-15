from decimal import Decimal

from django.test import TestCase

from domains.platform.core.utils import day_bounds_for_org, format_tenge, now_for_org, to_tenge
from domains.platform.tenants.models import Organization


class TimezoneUtilsTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(
            name="Балет Астана",
            slug="ballet-astana",
            timezone="Asia/Almaty",
        )

    def test_now_for_org_is_in_org_timezone(self):
        now = now_for_org(self.org)
        self.assertEqual(str(now.tzinfo), "Asia/Almaty")

    def test_day_bounds_evening_lesson_stays_in_same_day(self):
        import datetime

        import pytz

        tz = pytz.timezone("Asia/Almaty")
        evening = tz.localize(datetime.datetime(2026, 9, 14, 23, 0, 0))
        target_date = datetime.date(2026, 9, 14)

        start, end = day_bounds_for_org(self.org, date=target_date)

        self.assertGreaterEqual(evening, start)
        self.assertLessEqual(evening, end)

    def test_day_bounds_midnight_utc_stays_in_correct_day(self):
        import datetime

        import pytz

        tz = pytz.timezone("Asia/Almaty")
        midnight_utc = datetime.datetime(2026, 9, 15, 0, 0, 0, tzinfo=datetime.UTC)
        almaty_time = midnight_utc.astimezone(tz)
        target_date = almaty_time.date()  # 2026-09-15

        start, end = day_bounds_for_org(self.org, date=target_date)

        self.assertGreaterEqual(midnight_utc.astimezone(tz), start)
        self.assertLessEqual(midnight_utc.astimezone(tz), end)


class MoneyUtilsTest(TestCase):
    def test_to_tenge_integer(self):
        self.assertEqual(to_tenge(15000), Decimal("15000"))

    def test_to_tenge_string(self):
        self.assertEqual(to_tenge("15000"), Decimal("15000"))

    def test_to_tenge_rounds_up(self):
        self.assertEqual(to_tenge("15000.9"), Decimal("15001"))

    def test_to_tenge_rounds_down(self):
        self.assertEqual(to_tenge("15000.4"), Decimal("15000"))

    def test_to_tenge_not_float(self):
        result = to_tenge(15000)
        self.assertIsInstance(result, Decimal)
        self.assertNotIsInstance(result, float)

    def test_format_tenge(self):
        self.assertEqual(format_tenge(15000), "15 000 ₸")

    def test_format_tenge_large(self):
        self.assertEqual(format_tenge(1500000), "1 500 000 ₸")


class SoftDeleteCascadeTest(TestCase):
    def setUp(self):
        from domains.platform.tenants.models import Branch

        self.org = Organization.objects.create(
            name="Балет Астана",
            slug="ballet-astana",
        )
        self.branch = Branch.objects.create(
            name="Центральный",
            organization=self.org,
        )

    def test_soft_delete_hides_from_queryset(self):
        self.branch.delete()
        from domains.platform.tenants.models import Branch

        self.assertFalse(Branch.objects.filter(pk=self.branch.pk).exists())

    def test_soft_delete_visible_with_all_with_deleted(self):
        self.branch.delete()
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT deleted_at FROM tenants_branch WHERE id = %s", [str(self.branch.pk)]
            )
            row = cursor.fetchone()
        self.assertIsNotNone(row[0])

    def test_hard_delete_removes_physically(self):
        branch_id = str(self.branch.pk)
        self.branch.hard_delete()
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM tenants_branch WHERE id = %s", [branch_id])
            row = cursor.fetchone()
        self.assertIsNone(row)
