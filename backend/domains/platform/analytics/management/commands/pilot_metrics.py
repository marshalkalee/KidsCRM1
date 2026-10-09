"""
Метрики пилота «после» (ТЗ п. 11, критерий приёмки MVP № 10; TRU-152).

    python manage.py pilot_metrics --org true-ballet --from 2026-10-01 --to 2026-10-31

Считает из системы две метрики из трёх — теми же функциями, что и отчёты,
чтобы цифра совпала с экраном:

- конверсия заявок в пробное — воронка (analytics/funnel.py, TRU-115);
- известные центру задолженности — формула экрана «Задолженности»
  (money/subscriptions/debt.py, контракт № 5).

Третью — время администратора на рутину — система не знает: её дают
администратор и хронометраж (шаблон — docs/mvp-acceptance.md, раздел 4).
Печатает строки таблицы для docs/project-status.md.
"""

from datetime import date

from django.core.management.base import BaseCommand, CommandError

from domains.money.subscriptions.debt import debtor_subscriptions
from domains.platform.analytics.funnel import funnel
from domains.platform.analytics.period import Period
from domains.platform.analytics.scope import Scope
from domains.platform.tenants.models import Organization

TRIAL_STAGE = "trial_scheduled"


def pilot_metrics(organization, start: date, end: date) -> dict:
    result = funnel(Scope(organization, None), Period(start, end), compare=False)
    stages = {s["key"]: s["count"] for s in result["stages"]}
    total = result["total"]
    trials = stages.get(TRIAL_STAGE, 0)
    debts = list(debtor_subscriptions(organization))
    return {
        "leads": total,
        "trials": trials,
        "lead_to_trial_percent": round(100 * trials / total, 1) if total else None,
        "debt_subscriptions": len(debts),
        "debt_children": len({d.child_id for d in debts}),
        "debt_total": int(sum(getattr(d, "debt", 0) or 0 for d in debts)),
    }


class Command(BaseCommand):
    help = "Метрики пилота «после»: конверсия заявок в пробное и известные задолженности."

    def add_arguments(self, parser):
        parser.add_argument("--org", required=True, help="slug организации")
        parser.add_argument("--from", dest="start", required=True, help="ГГГГ-ММ-ДД")
        parser.add_argument("--to", dest="end", required=True, help="ГГГГ-ММ-ДД")

    def handle(self, *args, org, start, end, **options):
        organization = Organization.objects.filter(slug=org).first()
        if organization is None:
            raise CommandError(f"Нет организации со slug «{org}».")
        try:
            start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
        except ValueError as exc:
            raise CommandError("Даты в формате ГГГГ-ММ-ДД.") from exc
        m = pilot_metrics(organization, start_date, end_date)
        conversion = (
            f"{m['lead_to_trial_percent']} % ({m['trials']} из {m['leads']} заявок)"
            if m["lead_to_trial_percent"] is not None
            else "заявок за период нет"
        )
        period = f"{start_date:%d.%m.%Y}–{end_date:%d.%m.%Y}"
        self.stdout.write(f"Метрики «после» — {organization.name}, {period}\n")
        self.stdout.write("| Метрика | После (система) |")
        self.stdout.write("|---|---|")
        self.stdout.write(f"| Конверсия заявок в пробное | {conversion} |")
        total = f"{m['debt_total']:,}".replace(",", " ")
        self.stdout.write(
            f"| Известные задолженности (на сегодня) | детей: {m['debt_children']}, "
            f"абонементов: {m['debt_subscriptions']}, сумма: {total} ₸ |"
        )
        self.stdout.write(
            "| Время администратора на рутину | со слов администратора и хронометража — "
            "docs/mvp-acceptance.md, раздел 4 |"
        )
