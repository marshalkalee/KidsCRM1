"""
Единая точка правды "у ребёнка есть задолженность" (ТЗ п. 4.1, 4.4).

Используется фильтром списка детей (domains.people.clients), карточкой
родителя (parent_money) и экраном «Задолженности» (TRU-68) — если
посчитать в двух местах порознь, списки разойдутся и доверие к системе
на приёмке пропадёт. Долг — НЕ агрегат по ребёнку ("сумма минус общая
оплата"), а "есть хотя бы один абонемент, где цена больше суммы оплат
по нему": переплата по одному абонементу не гасит долг по другому.

payments/debt.py (TRU-66) считается устаревшим — использовал другую
формулу (сумма по ребёнку, с взаимозачётом между абонементами) и не
использовался ни одним реальным экраном. Не импортировать оттуда.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import F, Q, Sum
from django.db.models.functions import Coalesce

from domains.money.payments.models import Payment

from .models import Subscription

# Считать оплатой только подтверждённые, не отменённые — иначе отменённый
# (soft delete) или ещё не подтверждённый платёж молча уменьшает видимый
# долг. Sum() по обратной связи не проходит через менеджер Payment сам по
# себе — фильтр нужно указывать здесь явно, а не полагаться на for_tenant().
_CONFIRMED_PAYMENT = Q(payments__status=Payment.Status.CONFIRMED, payments__deleted_at__isnull=True)


def debtor_child_ids(organization):
    """Подзапрос id детей с хотя бы одним недоплаченным абонементом —
    предназначен для `Child.objects.filter(id__in=debtor_child_ids(org))`,
    не для материализации в Python (одним SQL-запросом на всю организацию,
    без разбора по строкам — ТЗ п. 10.2: фильтр должен работать на 5000
    детей за ≤1с)."""
    return (
        Subscription.objects.for_tenant(organization)
        .annotate(paid=Coalesce(Sum("payments__amount", filter=_CONFIRMED_PAYMENT), Decimal(0)))
        .filter(price__gt=F("paid"))
        .values("child_id")
    )


def debt_by_child(organization, child_ids) -> dict:
    """{child_id: сумма долга} — по тому же определению, что
    debtor_child_ids: по каждому абонементу max(0, цена − оплачено),
    переплата по одному абонементу не гасит долг по другому. Одним
    запросом на весь набор детей (список детей, карточка родителя) —
    в двух экранах одна и та же цифра."""
    rows = (
        Subscription.objects.for_tenant(organization)
        .filter(child_id__in=child_ids)
        .annotate(paid=Coalesce(Sum("payments__amount", filter=_CONFIRMED_PAYMENT), Decimal(0)))
        .filter(price__gt=F("paid"))
        .values_list("child_id", "price", "paid")
    )
    debts = {}
    for child_id, price, paid in rows:
        debts[child_id] = debts.get(child_id, Decimal(0)) + (price - paid)
    return debts


def debtor_subscriptions(organization, *, branch=None, direction=None, min_age_days=None):
    """Экран «Задолженности» (TRU-68) — та же формула долга, что и выше,
    одним запросом с фильтрами, по одной строке на КАЖДЫЙ недоплаченный
    абонемент (не агрегат по ребёнку — ТЗ явно просит колонку «абонемент»
    в списке, у одного ребёнка может быть два разных долга по двум
    направлениям одновременно)."""
    qs = (
        Subscription.objects.for_tenant(organization)
        .annotate(paid=Coalesce(Sum("payments__amount", filter=_CONFIRMED_PAYMENT), Decimal(0)))
        .filter(price__gt=F("paid"))
        .annotate(debt=F("price") - F("paid"))
        .select_related("child", "subscription_type_version", "direction", "branch")
    )
    if branch:
        qs = qs.filter(branch=branch)
    if direction:
        qs = qs.filter(direction=direction)
    if min_age_days is not None:
        cutoff = date.today() - timedelta(days=min_age_days)
        qs = qs.filter(starts_on__lte=cutoff)
    return qs


def debt_age_days(subscription: Subscription) -> int:
    """Давность — от даты продажи (starts_on): отдельного поля 'плановая
    дата оплаты' в модели нет. Появится — поправить только здесь."""
    return (date.today() - subscription.starts_on).days
