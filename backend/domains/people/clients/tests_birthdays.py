"""Дни рождения на главной (clients/birthdays.py): ближайшие дни, переход
через Новый год, 29 февраля, только те, кто ходит, только свой центр."""

import datetime
from unittest import mock

from django.test import TestCase, tag
from rest_framework.test import APIClient

from domains.platform.tenants.models import Organization
from domains.platform.users.models import User

from .birthdays import upcoming_birthdays
from .models import Child


class BirthdaysTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Центр", slug="bd")
        self.today = datetime.date(2026, 12, 29)
        patcher = mock.patch(
            "domains.people.clients.birthdays.today_for_org", return_value=self.today
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def child(self, name, birth_date, status=Child.Status.ACTIVE, org=None):
        return Child.objects.create(
            organization=org or self.org, full_name=name, birth_date=birth_date, status=status
        )

    def test_window_order_and_age(self):
        self.child("Сегодня", datetime.date(2016, 12, 29))
        self.child("Через Новый год", datetime.date(2018, 1, 3))
        self.child("Далеко", datetime.date(2018, 1, 20))
        self.child("Было вчера", datetime.date(2017, 12, 28))
        rows = upcoming_birthdays(self.org, days=7)
        self.assertEqual(
            [(r["full_name"], r["days_until"], r["turns"]) for r in rows],
            [("Сегодня", 0, 10), ("Через Новый год", 5, 9)],
        )
        self.assertEqual(rows[1]["date"], "2027-01-03")

    def test_only_attending_children(self):
        self.child("Ушла", datetime.date(2016, 12, 30), status=Child.Status.LEFT)
        self.child("На паузе", datetime.date(2016, 12, 30), status=Child.Status.PAUSED)
        self.child("Пробное", datetime.date(2016, 12, 30), status=Child.Status.TRIAL)
        self.assertEqual([r["full_name"] for r in upcoming_birthdays(self.org)], ["Пробное"])

    def test_leap_day_in_common_year(self):
        with mock.patch(
            "domains.people.clients.birthdays.today_for_org",
            return_value=datetime.date(2027, 2, 27),
        ):
            self.child("Високосная", datetime.date(2016, 2, 29))
            rows = upcoming_birthdays(self.org, days=3)
        self.assertEqual((rows[0]["date"], rows[0]["turns"]), ("2027-02-28", 11))

    @tag("tenant_isolation")
    def test_api_shows_only_own_center(self):
        other = Organization.objects.create(name="Чужой", slug="bd-other")
        self.child("Свой", datetime.date(2016, 12, 30))
        self.child("Чужой", datetime.date(2016, 12, 30), org=other)
        teacher = User.objects.create_user(
            phone="+77010000077",
            password="x",
            full_name="Педагог",
            organization=self.org,
            role=User.Role.TEACHER,
        )
        client = APIClient()
        client.force_authenticate(teacher)
        response = client.get("/api/v1/clients/children/birthdays/", {"days": 7})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([r["full_name"] for r in response.data], ["Свой"])
