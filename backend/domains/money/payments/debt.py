"""
Расчёт задолженности (ТЗ п. 3.1) — единый сервис для всех экранов
(контракт №5, см. backend/docs/contracts.md). Долг = цена СО СКИДКОЙ
(Subscription.price) минус подтверждённые оплаты, не прайсовая цена.

Не клэмпится к нулю намеренно: отрицательное значение — переплата,
это реальная бухгалтерская ситуация, а не ошибка отображения.

Отменённые оплаты (soft delete, TRU-64) не уменьшают долг — обычный
for_tenant() их не видит. Неподтверждённые (PENDING/REJECTED, TRU-65)
тоже не считаются — деньги ещё не признаны поступившими.

Долг по ребёнку — по ВСЕМ его абонементам, независимо от статуса.

debt_for_parent(): родитель — обязательно единственный активный
плательщик на ребёнка (ChildContact.is_payer, инвариант согласован
с Bekzat, feature/child-parent-link) — делить долг между несколькими
плательщиками не нужно, их не может быть больше одного.
"""

from datetime import date

from django.db.models import Sum

from domains.money.payments.models import Payment
from domains.money.subscriptions.models import Subscription


def debt_for_subscription(subscription: Subscription):
    paid = (
        Payment.objects.for_tenant(subscription.organization)
        .filter(subscription=subscription, status=Payment.Status.CONFIRMED)
        .aggregate(total=Sum("amount"))["total"]
        or 0
    )
    return subscription.price - paid


def debt_for_children(children) -> int:
    """Единственное реальное место суммирования — debt_for_child и
    debt_for_parent обязаны звать именно её, а не считать заново."""
    child_ids = (
        [c.pk for c in children]
        if not hasattr(children, "values_list")
        else children.values_list("pk", flat=True)
    )
    subscriptions = Subscription.objects.filter(child_id__in=child_ids).select_related(
        "subscription_type_version"
    )
    return sum(debt_for_subscription(sub) for sub in subscriptions)


def debt_for_child(child) -> int:
    return debt_for_children([child])


def debt_for_parent(parent_contact) -> int:
    from domains.people.clients.models import Child

    children = Child.objects.filter(
        contacts__parent_contact=parent_contact,
        contacts__is_payer=True,
        contacts__deleted_at__isnull=True,
    )
    return debt_for_children(children)


def debt_for_branch(branch) -> int:
    subscriptions = Subscription.objects.for_tenant(branch.organization).filter(branch=branch)
    return sum(debt_for_subscription(sub) for sub in subscriptions)


def debt_age_days(subscription: Subscription) -> int:
    """Давность — от даты продажи (starts_on): отдельного поля 'плановая
    дата оплаты' в модели нет. Появится — поправить только здесь."""
    return (date.today() - subscription.starts_on).days
