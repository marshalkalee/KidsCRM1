"""
Единая точка правды "у ребёнка есть задолженность" (ТЗ п. 4.1, 4.4).

Используется фильтром списка детей (domains.people.clients), карточкой
родителя (parent_money) и экраном «Задолженности» (TRU-68) — если
посчитать в двух местах порознь, списки разойдутся и доверие к системе
на приёмке пропадёт. Долг — НЕ агрегат по ребёнку ("сумма минус общая
оплата"), а "есть хотя бы один абонемент, где цена больше суммы оплат
по нему": переплата по одному абонементу не гасит долг по другому.

Второго расчёта нет: payments/debt.py (TRU-66) со взаимозачётом между
абонементами удалён в TRU-73. Экран оплаты, вкладки карточки и отчёты
берут долг только отсюда.
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import F, Q, Sum
from django.db.models.functions import Coalesce

from domains.money.payments.models import Payment
from domains.platform.core.utils import today_for_org

from .models import Subscription

# Считать оплатой только подтверждённые, не отменённые — иначе отменённый
# (soft delete) или ещё не подтверждённый платёж молча уменьшает видимый
# долг. Sum() по обратной связи не проходит через менеджер Payment сам по
# себе — фильтр нужно указывать здесь явно, а не полагаться на for_tenant().
_CONFIRMED_PAYMENT = Q(payments__status=Payment.Status.CONFIRMED, payments__deleted_at__isnull=True)


def paid_sum():
    """Сколько оплачено по абонементу — для .annotate(paid=paid_sum())."""
    return Coalesce(Sum("payments__amount", filter=_CONFIRMED_PAYMENT), Decimal(0))


def subscription_debt(subscription) -> Decimal:
    """Долг по одному абонементу, по той же формуле, что списки: не меньше
    нуля. Берёт annotate(paid=…), если он есть, иначе считает сам."""
    paid = getattr(subscription, "paid", None)
    if paid is None:
        paid = Subscription.objects.filter(pk=subscription.pk).aggregate(paid=paid_sum())["paid"]
    return max(subscription.price - paid, Decimal(0))


def debtor_child_ids(organization):
    """Подзапрос id детей с хотя бы одним недоплаченным абонементом —
    предназначен для `Child.objects.filter(id__in=debtor_child_ids(org))`,
    не для материализации в Python (одним SQL-запросом на всю организацию,
    без разбора по строкам — ТЗ п. 10.2: фильтр должен работать на 5000
    детей за ≤1с)."""
    return (
        Subscription.objects.for_tenant(organization)
        .annotate(paid=paid_sum())
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
        .annotate(paid=paid_sum())
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
        .annotate(paid=paid_sum())
        .filter(price__gt=F("paid"))
        .annotate(debt=F("price") - F("paid"))
        .select_related("child", "subscription_type_version", "direction", "branch")
    )
    if branch:
        qs = qs.filter(branch=branch)
    if direction:
        qs = qs.filter(direction=direction)
    if min_age_days is not None:
        cutoff = today_for_org(organization) - timedelta(days=min_age_days)
        qs = qs.filter(starts_on__lte=cutoff)
    return qs


def debt_age_days(subscription: Subscription) -> int:
    """Давность — от даты продажи (starts_on): отдельного поля 'плановая
    дата оплаты' в модели нет. Появится — поправить только здесь."""
    return (today_for_org(subscription.organization) - subscription.starts_on).days


def debt_for_child(organization, child_id) -> Decimal:
    """Долг одного ребёнка — тонкая обёртка над debt_by_child для мест,
    где нужен ровно один ребёнок, не список (например, вкладка «Оплаты»)."""
    return debt_by_child(organization, [child_id]).get(child_id, Decimal(0))


def debt_for_parent(organization, parent) -> Decimal:
    """Долг родителя — сумма по ВСЕМ привязанным детям (любая роль в
    ChildContact, не только is_payer) — так уже считает карточка
    родителя (people.clients.parents.parent_money); эта функция даёт то
    же самое через общий debt_by_child, а не отдельную формулу."""
    from domains.people.clients.models import ChildContact

    child_ids = list(
        ChildContact.objects.for_tenant(organization)
        .filter(parent_contact=parent, child__deleted_at__isnull=True)
        .values_list("child_id", flat=True)
    )
    return sum(debt_by_child(organization, child_ids).values(), Decimal(0))


def debt_total(organization, *, branch_ids=None) -> Decimal:
    """Сумма долга по организации или набору филиалов — для аналитики
    (TRU-118): та же формула, что debtor_subscriptions, но одним агрегатом
    в базе, без строк. Цифра дашборда = итог экрана «Задолженности»."""
    qs = (
        Subscription.objects.for_tenant(organization)
        .annotate(paid=paid_sum())
        .filter(price__gt=F("paid"))
    )
    if branch_ids is not None:
        qs = qs.filter(branch_id__in=branch_ids)
    # Складываем в Python: Django не суммирует выражение поверх агрегата
    # paid_sum() в одном SELECT, а своя формула «оплачено» через подзапрос
    # была бы вторым определением долга. Строк — только должники (сотни,
    # не десятки тысяч), замер в ADR-0006.
    rows = qs.values_list("price", "paid")
    return sum((price - paid for price, paid in rows), Decimal(0))


def create_tasks_for_overdue_debt() -> int:
    """Автоправило: задолженность старше N дней → «напомнить об оплате»
    (ТЗ п. 5.2, TRU-108). Идемпотентность — через source_key на Task."""
    from domains.platform.tasks.models import RuleRun, Task
    from domains.platform.tasks.services import create_task
    from domains.platform.tenants.models import Organization
    from domains.platform.tenants.org_settings import (
        DEBT_OVERDUE_DAYS_THRESHOLD,
        RULE_DEBT_REMINDER_ENABLED,
        get_org_setting,
    )

    created = 0
    for organization in Organization.objects.all():
        if not get_org_setting(organization, RULE_DEBT_REMINDER_ENABLED):
            continue
        threshold_days = get_org_setting(organization, DEBT_OVERDUE_DAYS_THRESHOLD)
        created_for_org = 0
        for subscription in debtor_subscriptions(organization, min_age_days=threshold_days):
            task = create_task(
                type=Task.Type.PAYMENT_REMINDER,
                assignee=None,
                due_date=None,
                subject=f"Напомнить об оплате: {subscription.child.full_name}",
                organization=organization,
                source=Task.Source.AUTO,
                branch=subscription.branch,
                child=subscription.child,
                source_key=f"debt_reminder:{subscription.id}",
            )
            if task is not None:
                created_for_org += 1
        if created_for_org:
            RuleRun.objects.create(
                organization=organization, rule="debt_reminder", tasks_created=created_for_org
            )
        created += created_for_org
    return created
