"""
Приём и отмена оплаты (ТЗ п. 3.1, 3.2, 4.4). Суммы — только через
to_tenge() (TRU-17), никогда напрямую Decimal(str(...)) — иначе дробные
тенге проскочат мимо инварианта "целые числа" (ТЗ п. 3.2).

Отмена — soft delete (deleted_at), не физическое удаление (критерий
приёмки MVP №8): отменённая оплата остаётся в базе и в истории.
"""

from datetime import datetime, time

import pytz
from django.db import transaction
from django.utils import timezone

from domains.platform.core.audit import AuditLog
from domains.platform.core.utils import today_for_org

from .models import Payment

# Время, которым фиксируется оплата прошлым днём: середина дня по часовому
# поясу центра — дата не уедет на соседний день ни в отчётах по поясу центра,
# ни в выборках по UTC.
BACKDATED_PAYMENT_TIME = time(12, 0)


def paid_at_for(organization, paid_on=None):
    """Дата оплаты (TRU-131) → момент paid_at. Пусто или сегодня — сейчас;
    прошлый день — полдень по поясу центра; будущая дата — ошибка."""
    today = today_for_org(organization)
    if paid_on is None or paid_on == today:
        return timezone.now()
    if paid_on > today:
        raise ValueError("Дата оплаты не может быть в будущем.")
    tz = pytz.timezone(organization.timezone)
    return tz.localize(datetime.combine(paid_on, BACKDATED_PAYMENT_TIME))


@transaction.atomic
def record_payment(
    *,
    actor,
    subscription,
    amount,
    method,
    payer=None,
    comment="",
    idempotency_key=None,
    paid_on=None,
) -> Payment:
    from .providers import ManualProvider

    return ManualProvider(method).record(
        subscription=subscription,
        amount=amount,
        actor=actor,
        payer=payer,
        comment=comment,
        idempotency_key=idempotency_key,
        paid_at=paid_at_for(subscription.organization, paid_on),
    )


@transaction.atomic
def cancel_payment(payment: Payment, *, actor, reason: str) -> Payment:
    # Строка блокируется до конца транзакции: два одновременных запроса
    # отмены не пройдут оба, второй увидит deleted_at первого (TRU-131).
    deleted_at = (
        Payment.objects.all_with_deleted()
        .select_for_update()
        .values_list("deleted_at", flat=True)
        .get(pk=payment.pk)
    )
    if deleted_at is not None:
        raise ValueError("Оплата уже отменена")

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
