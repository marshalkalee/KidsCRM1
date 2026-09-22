"""
Единая точка правды "у ребёнка есть задолженность" (ТЗ п. 4.1, 4.4).

Используется фильтром списка детей (domains.people.clients) и будущим
экраном «Задолженности» (Bekzat) — если посчитать в двух местах порозь,
списки разойдутся и доверие к системе на приёмке пропадёт (явное
требование тикета "Фильтры списка детей"). Долг — это НЕ агрегат по
ребёнку ("сумма минус общая оплата"), а "есть хотя бы один абонемент,
где цена больше суммы оплат по нему" — так же считает _batch_child_extras
(domains.people.clients.web_views) при выводе колонки "Долг".
"""

from decimal import Decimal

from django.db.models import F, Sum
from django.db.models.functions import Coalesce

from .models import Subscription


def debtor_child_ids(organization):
    """Подзапрос id детей с хотя бы одним недоплаченным абонементом —
    предназначен для `Child.objects.filter(id__in=debtor_child_ids(org))`,
    не для материализации в Python (одним SQL-запросом на всю организацию,
    без разбора по строкам — ТЗ п. 10.2: фильтр должен работать на 5000
    детей за ≤1с)."""
    return (
        Subscription.objects.for_tenant(organization)
        .annotate(paid=Coalesce(Sum("payments__amount"), Decimal(0)))
        .filter(price__gt=F("paid"))
        .values("child_id")
    )
