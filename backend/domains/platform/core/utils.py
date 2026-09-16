from decimal import ROUND_HALF_UP, Decimal

import pytz
from django.utils import timezone


def now_for_org(organization):
    tz = pytz.timezone(organization.timezone)
    return timezone.now().astimezone(tz)


def today_for_org(organization):
    return now_for_org(organization).date()


def day_bounds_for_org(organization, date=None):
    tz = pytz.timezone(organization.timezone)
    target_date = date or today_for_org(organization)

    start = tz.localize(
        timezone.datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0)
    )
    end = tz.localize(
        timezone.datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59, 999999)
    )
    return start, end


def to_tenge(value):
    return Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def format_tenge(value):
    amount = to_tenge(value)
    formatted = f"{amount:,}".replace(",", " ")
    return f"{formatted} ₸"
