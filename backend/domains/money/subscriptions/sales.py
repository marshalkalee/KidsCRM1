"""
Продажа абонемента — одна атомарная операция (ТЗ п. 4.4): Subscription с
зафиксированной ценой/скидкой + начисление в журнал + Payment + аудит-лог.
Частичный сбой посередине недопустим — либо продажа целиком, либо ничего.
"""

from datetime import timedelta

from django.db import transaction

from domains.money.payments.services import record_payment
from domains.platform.core.audit import AuditLog
from domains.platform.leads.services import close_renewal_on_sale

from .models import Subscription, SubscriptionLedgerEntry
from .subscriptions import add_ledger_entry


@transaction.atomic
def sell_subscription(
    *,
    actor,
    child,
    subscription_type_version,
    direction,
    branch,
    starts_on,
    discount_amount=0,
    discount_reason="",
    discount_comment="",
    paid_amount,
    payment_method,
    comment="",
):
    list_price = subscription_type_version.price
    # Скидка больше цены давала отрицательную стоимость абонемента (TRU-131).
    if discount_amount < 0 or discount_amount > list_price:
        raise ValueError("Скидка должна быть от 0 до стоимости абонемента.")
    if discount_amount and not discount_reason:
        raise ValueError("Скидка без причины не допускается")

    ends_on = starts_on + timedelta(days=subscription_type_version.duration_days)
    subscription = Subscription.objects.create(
        organization=child.organization,
        child=child,
        subscription_type_version=subscription_type_version,
        direction=direction,
        branch=branch,
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

    payment = None
    if paid_amount and paid_amount > 0:
        from domains.people.clients.models import ChildContact

        current_payer_link = ChildContact.objects.filter(child=child, is_payer=True).first()
        payment = record_payment(
            actor=actor,
            subscription=subscription,
            amount=paid_amount,
            method=payment_method,
            payer=current_payer_link.parent_contact if current_payer_link else None,
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
    # Клиента удержали — заявка-продление, если была, закрыта продажей (TRU-98).
    close_renewal_on_sale(
        child, actor=actor, subscription_name=subscription_type_version.subscription_type.name
    )
    return subscription, payment
