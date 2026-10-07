"""
Сводка расхода ИИ по всем центрам за месяц — для платформы, не для
центров (TRU-160). Из неё — себестоимость опции перед установкой цены.

    python manage.py ai_usage_report               # текущий месяц
    python manage.py ai_usage_report --month 2026-10
"""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Sum
from django.utils import timezone

from domains.platform.ai import usage
from domains.platform.tenants.models import Organization


class Command(BaseCommand):
    help = "Расход ИИ по организациям за месяц: запросы, токены, $ и ₸, доля лимита."

    def add_arguments(self, parser):
        parser.add_argument("--month", help="ГГГГ-ММ, по умолчанию текущий")

    def handle(self, *args, month=None, **options):
        if month:
            try:
                year, number = (int(part) for part in month.split("-"))
                # Середина месяца: границы считаются в поясе каждого центра.
                moment = datetime(year, number, 15, 12, tzinfo=ZoneInfo("UTC"))
            except ValueError as exc:
                raise CommandError("--month в формате ГГГГ-ММ, например 2026-10") from exc
        else:
            moment = timezone.now()

        header = "Центр".ljust(32) + " ".join(
            name.rjust(width)
            for name, width in [
                ("запр.", 7),
                ("вход", 10),
                ("выход", 9),
                ("$", 9),
                ("₸", 8),
                ("лимит", 6),
            ]
        )
        self.stdout.write(f"Расход ИИ за {moment:%Y-%m}\n{header}")
        total_usd = Decimal(0)
        active = 0
        for organization in Organization.objects.order_by("name"):
            totals = usage.month_rows(organization, moment).aggregate(
                calls=Count("id"),
                inp=Sum("input_tokens"),
                out=Sum("output_tokens"),
                cost=Sum("cost_usd"),
            )
            if not totals["calls"]:
                continue
            active += 1
            cost = totals["cost"] or Decimal(0)
            total_usd += cost
            kzt = usage.to_kzt(cost)
            limit = usage.limit_kzt(organization)
            share = round(100 * kzt / limit) if limit else 0
            self.stdout.write(
                f"{organization.name[:32]:<32} {totals['calls']:>6} {totals['inp'] or 0:>10} "
                f"{totals['out'] or 0:>9} {cost:>9.2f} {kzt:>8} {share:>5}%"
            )
        if not active:
            self.stdout.write("Обращений к ИИ за месяц не было.")
            return
        average = total_usd / active
        self.stdout.write(
            f"\nИтого: ${total_usd:.2f} ({usage.to_kzt(total_usd)} ₸), "
            f"центров с расходом: {active}, "
            f"в среднем на центр: ${average:.2f} ({usage.to_kzt(average)} ₸)"
        )
