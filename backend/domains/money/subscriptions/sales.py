"""
Продажа абонемента — одна атомарная операция (ТЗ п. 4.4): Subscription с
зафиксированной ценой/скидкой + начисление в журнал + Payment + аудит-лог.
Частичный сбой посередине недопустим — либо продажа целиком, либо ничего.
"""

from django.db import transaction

from domains.money.payments.services import record_payment
from domains.platform.core.audit import AuditLog

from .models import Subscription, SubscriptionLedgerEntry
from .subscriptions import add_ledger_entry


@transaction.atomic
def sell_subscription(
    *,
    actor,
    child,
    subscription_type_version,
    direction,
    starts_on,
    ends_on,
    discount_amount=0,
    discount_reason="",
    discount_comment="",
    paid_amount,
    payment_method,
    comment="",
):
    if discount_amount and not discount_reason:
        raise ValueError("Скидка без причины не допускается")

    list_price = subscription_type_version.price
    subscription = Subscription.objects.create(
        organization=child.organization,
        child=child,
        subscription_type_version=subscription_type_version,
        direction=direction,
        starts_on=starts_on,
        ends_on=ends_on,
        status=Subscription.Status.ACTIVE,
        list_price=list_price,
        discount_amount=discount_amount,
        discount_reason=discount_reason,
        discount_comment=discount_comment,
        price=list_price - discount_amount,
    )

    if not subscription_type_version.is_unlimited:
        add_ledger_entry(
            subscription,
            kind=SubscriptionLedgerEntry.Kind.INITIAL_GRANT,
            delta=subscription_type_version.quota_sessions,
        )

    payment = record_payment(
        actor=actor,
        subscription=subscription,
        amount=paid_amount,
        method=payment_method,
        comment=comment,
    )

    AuditLog.record(
        actor=actor,
        action=AuditLog.Action.CREATE,
        entity=subscription,
        after={
            "child": str(child),
            "list_price": str(list_price),
            "discount_amount": str(discount_amount),
            "discount_reason": discount_reason,
            "price": str(subscription.price),
            "paid_amount": str(paid_amount),
        },
    )
    return subscription, payment
