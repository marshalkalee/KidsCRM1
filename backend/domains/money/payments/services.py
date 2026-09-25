"""
Приём и отмена оплаты (ТЗ п. 3.1, 3.2, 4.4). Суммы — только через
to_tenge() (TRU-17), никогда напрямую Decimal(str(...)) — иначе дробные
тенге проскочат мимо инварианта "целые числа" (ТЗ п. 3.2).

Отмена — soft delete (deleted_at), не физическое удаление (критерий
приёмки MVP №8): отменённая оплата остаётся в базе и в истории.
"""

from django.db import transaction

from domains.platform.core.audit import AuditLog

from .models import Payment


@transaction.atomic
def record_payment(
    *, actor, subscription, amount, method, comment="", idempotency_key=None
) -> Payment:
    from .providers import ManualProvider

    return ManualProvider(method).record(
        subscription=subscription,
        amount=amount,
        actor=actor,
        comment=comment,
        idempotency_key=idempotency_key,
    )


@transaction.atomic
def cancel_payment(payment: Payment, *, actor, reason: str) -> Payment:
    before = {"amount": str(payment.amount), "cancelled": False}
    payment.cancelled_reason = reason
    payment.save(update_fields=["cancelled_reason"])
    payment.delete()  # soft delete (TimestampedSoftDeleteModel) — не физическое

    AuditLog.record(
        actor=actor,
        action=AuditLog.Action.DELETE,
        entity=payment,
        before=before,
        after={"cancelled": True, "reason": reason},
    )
    return payment
