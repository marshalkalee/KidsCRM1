"""
Отчёт по источникам заявок (TRU-116, ТЗ раздел 7: «качество источников»).

Вопрос владельца — не «откуда больше заявок», а «откуда приходят клиенты»:
источник с десятью заявками и пятью покупками лучше сотни заявок и трёх
покупок. Поэтому по каждому источнику — та же воронка (когорта новых
заявок за период, TRU-115): сколько дошли до пробного, сколько купили,
конверсия и средний чек проданного из заявки абонемента.

Стоимость источника (сколько стоила заявка и клиент) не считаем: расходов
на рекламу в системе нет. На экране это сказано прямо — отчёт показывает
качество, а не окупаемость.

Малая выборка: меньше SMALL_SAMPLE заявок — конверсия помечается, иначе
владелец закроет канал по трём заявкам.
"""

import uuid
from collections import defaultdict
from decimal import Decimal

import pytz
from django.db.models.functions import TruncMonth

from domains.platform.leads.models import Lead, LeadCampaign

from .breakdowns import DIMENSIONS
from .funnel import _history, _stage_counts, cohort
from .registry import cached

S = Lead.Status
SMALL_SAMPLE = 20


def _pct(part, whole):
    return round(part * 100 / whole, 1) if whole else None


def sources_quality(scope, period, filters=None):
    """[{key, label, leads, trial, purchased, trial_rate, conversion,
    avg_check, revenue, small_sample}] — по убыванию покупок."""
    return _quality(scope, period, filters, "source_id", DIMENSIONS["source"], "sq")


def _campaign_labels(organization, keys):
    rows = LeadCampaign.objects.for_tenant(organization).filter(pk__in=[k for k in keys if k])
    return {c.pk: f"{c.name} · {c.code}" for c in rows.select_related("source")}


def campaigns_quality(scope, period, filters=None):
    """То же по публикациям (TRU-165): какой ролик приводит клиентов. Только
    заявки с публикацией — без неё строки «не указано» нет, это видно в
    отчёте по источникам."""
    items = _quality(scope, period, filters, "campaign_id", _campaign_labels, "cq")
    sources = dict(
        LeadCampaign.objects.for_tenant(scope.organization).values_list("pk", "source__name")
    )
    return [
        {**item, "source": sources.get(uuid.UUID(item["key"]))} for item in items if item["key"]
    ]


def _quality(scope, period, filters, field, labels_of, cache_prefix):
    def run():
        rows = list(
            cohort(scope, period, filters).values_list(
                "id", "status", field, "sold_subscription__price"
            )
        )
        history = _history([row[0] for row in rows])
        groups = defaultdict(list)
        for lead_id, status, source_id, price in rows:
            groups[source_id].append((lead_id, status, price))
        labels = labels_of(scope.organization, list(groups))
        items = []
        for source_id, group in groups.items():
            counts, _ = _stage_counts([(lead_id, status) for lead_id, status, _ in group], history)
            leads = len(group)
            prices = [price for _, status, price in group if price is not None]
            revenue = sum(prices, Decimal(0))
            items.append(
                {
                    "key": str(source_id) if source_id else None,
                    "label": labels.get(source_id) if source_id else None,
                    "leads": leads,
                    "trial": counts[S.TRIAL_ATTENDED],
                    "purchased": counts[S.PURCHASED],
                    "trial_rate": _pct(counts[S.TRIAL_ATTENDED], leads),
                    "conversion": _pct(counts[S.PURCHASED], leads),
                    # Средний чек — по абонементам, проданным прямо из заявки.
                    "avg_check": str(round(revenue / len(prices))) if prices else None,
                    "revenue": str(revenue),
                    "small_sample": leads < SMALL_SAMPLE,
                }
            )
        return sorted(
            items,
            key=lambda item: (
                -item["purchased"],
                -(item["conversion"] or 0),
                item["label"] is None,
            ),
        )

    key = (
        f"{cache_prefix}:{scope.cache_key}:{period.start}:{period.end}:"
        f"{sorted((filters or {}).items())}"
    )
    return cached(key, period, scope, run)


def sources_by_month(scope, period, filters=None):
    """Заявки и покупки по месяцу создания заявки и источнику — тренд
    каналов. [{month, source, label, leads, purchased}]."""

    def run():
        tz = pytz.timezone(scope.organization.timezone)
        rows = list(
            cohort(scope, period, filters)
            .annotate(month=TruncMonth("created_at", tzinfo=tz))
            .values_list("id", "status", "source_id", "month")
        )
        history = _history([row[0] for row in rows])
        buckets = defaultdict(list)
        for lead_id, status, source_id, month in rows:
            buckets[(month.date().replace(day=1), source_id)].append((lead_id, status))
        labels = DIMENSIONS["source"](scope.organization, list({key[1] for key in buckets}))
        result = []
        for (month, source_id), group in sorted(buckets.items(), key=lambda kv: kv[0][0]):
            counts, _ = _stage_counts(group, history)
            result.append(
                {
                    "month": month.isoformat(),
                    "source": str(source_id) if source_id else None,
                    "label": labels.get(source_id) if source_id else None,
                    "leads": len(group),
                    "purchased": counts[S.PURCHASED],
                }
            )
        return result

    key = f"sm:{scope.cache_key}:{period.start}:{period.end}:{sorted((filters or {}).items())}"
    return cached(key, period, scope, run)
