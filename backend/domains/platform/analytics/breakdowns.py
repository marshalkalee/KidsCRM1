"""
Разбивки метрик и тепловая карта (TRU-113, поверх реестра TRU-118).

Разбивка — та же метрика за тот же период, разложенная по одному
измерению: выручка по способу оплаты, посещения по филиалам, заявки по
источникам. Сумма разбивки = значение метрики (кроме «разных детей»).
"""

import pytz
from django.db.models import Count
from django.db.models.functions import ExtractHour, ExtractIsoWeekDay

from domains.money.payments.models import Payment
from domains.money.subscriptions.models import SubscriptionType
from domains.platform.leads.models import LeadSource
from domains.platform.tenants.models import Branch, Direction
from domains.platform.users.models import User
from domains.scheduling.attendance.models import Attendance
from domains.scheduling.groups.models import Group

from .metrics import visits
from .registry import REGISTRY, cached


def _names(model):
    def resolve(organization, keys):
        rows = model.objects.for_tenant(organization).filter(pk__in=[k for k in keys if k])
        return {row.pk: row.name for row in rows}

    return resolve


def _staff(organization, keys):
    rows = User.objects.filter(organization=organization, pk__in=[k for k in keys if k])
    return {row.pk: row.full_name for row in rows}


def _choices(choices):
    labels = dict(choices)
    return lambda organization, keys: {key: labels.get(key, key) for key in keys}


# Подписи ключей: филиалы и направления — по имени из базы, способы оплаты
# и статусы посещения — русские подписи моделей (фронт переводит по ключу).
DIMENSIONS = {
    "branch": _names(Branch),
    "direction": _names(Direction),
    "source": _names(LeadSource),
    "method": _choices(Payment.Method.choices),
    "status": _choices(Attendance.Status.choices),
    "reason": _choices(Attendance.AbsenceReason.choices),
    "group": _names(Group),
    "teacher": _staff,
    "subscription_type": _names(SubscriptionType),
    "client": _choices([("new", "Новые клиенты"), ("renewal", "Продления")]),
}


class BreakdownError(ValueError):
    pass


def breakdown(name, dimension, scope, period):
    metric = REGISTRY.get(name)
    if metric is None or dimension not in (getattr(metric, "breakdowns", None) or {}):
        raise BreakdownError(f"У метрики {name} нет разбивки «{dimension}».")

    def run():
        rows = metric.breakdown(scope, period, dimension)
        labels = DIMENSIONS[dimension](scope.organization, [key for key, _ in rows])
        return [
            {
                # Пустая причина пропуска — как «не указано», а не отдельный ключ "".
                "key": str(key) if key not in (None, "") else None,
                "label": labels.get(key) if key not in (None, "") else None,
                "value": str(value) if not isinstance(value, int) else value,
            }
            for key, value in rows
        ]

    key = f"b:{name}:{dimension}:{scope.cache_key}:{period.start}:{period.end}"
    return cached(key, period, scope, run)


def visits_heatmap(scope, period):
    """Посещения по дню недели (1 — пн) и часу начала занятия, в поясе центра:
    когда центр загружен, а когда залы пустуют."""

    def run():
        tz = pytz.timezone(scope.organization.timezone)
        start, end = period.bounds(scope.organization)
        rows = (
            visits(scope)
            .filter(lesson__starts_at__gte=start, lesson__starts_at__lt=end)
            .order_by()
            .annotate(
                weekday=ExtractIsoWeekDay("lesson__starts_at", tzinfo=tz),
                hour=ExtractHour("lesson__starts_at", tzinfo=tz),
            )
            .values("weekday", "hour")
            .annotate(v=Count("id"))
            .values_list("weekday", "hour", "v")
        )
        return [{"weekday": w, "hour": h, "value": v} for w, h, v in rows]

    key = f"h:visits:{scope.cache_key}:{period.start}:{period.end}"
    return cached(key, period, scope, run)
