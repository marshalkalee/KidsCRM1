"""
Абстракция провайдера оплаты (ТЗ п. 4.4 — задел под эквайринг, BACKLOG,
ТЗ п. 12). Ручная фиксация — ManualProvider, один из провайдеров, а не
единственный путь в коде. Будущий эквайринг реализует тот же протокол
и пишет в те же поля Payment — без переделки модели (см. ADR-003).
"""

from abc import ABC, abstractmethod

from django.utils import timezone

from domains.platform.core.audit import AuditLog
from domains.platform.core.utils import to_tenge

from .models import Payment


class PaymentProvider(ABC):
    @abstractmethod
    def record(self, *, subscription, amount, actor, comment="") -> Payment: ...


class ManualProvider(PaymentProvider):
    """Единственный реализованный в MVP: администратор сам видит поступление
    (Kaspi-перевод/наличные/карта) и фиксирует вручную. Сразу CONFIRMED —
    человек уже проверил оплату глазами, ждать подтверждения не от кого."""

    def __init__(self, method: str):
        self.method = method

    def record(self, *, subscription, amount, actor, comment="", idempotency_key=None) -> Payment:
        now = timezone.now()
        defaults = dict(
            organization=subscription.organization,
            subscription=subscription,
            amount=to_tenge(amount),
            method=self.method,
            status=Payment.Status.CONFIRMED,
            confirmed_at=now,
            received_by=actor,
            comment=comment,
        )
        if idempotency_key:
            payment, created = Payment.objects.get_or_create(
                provider=Payment.Provider.MANUAL,
                provider_transaction_id=str(idempotency_key),
                defaults=defaults,
            )
        else:
            payment = Payment.objects.create(
                provider=Payment.Provider.MANUAL,
                provider_transaction_id=None,
                **defaults,
            )
            created = True

        if created:
            AuditLog.record(
                actor=actor,
                action=AuditLog.Action.CREATE,
                entity=payment,
                after={"amount": str(payment.amount), "method": self.method, "provider": "manual"},
            )
        return payment
