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
        if to_tenge(amount) <= 0:
            raise ValueError("Сумма оплаты должна быть больше нуля.")
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
            # Ключ присылает клиент — с префиксом организации, чтобы ключ
            # чужого центра не вернул его оплату и не упёрся в unique.
            payment, created = Payment.objects.get_or_create(
                provider=Payment.Provider.MANUAL,
                provider_transaction_id=f"{subscription.organization_id}:{idempotency_key}",
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


class KaspiPayProvider(PaymentProvider):
    """Оплата по счёту Kaspi (PaymentRequest): деньги пришли удалённо.
    Сразу CONFIRMED — оплату подтвердил шлюз Kaspi или администратор,
    увидевший поступление. transaction_id — номер операции Kaspi (или
    счёта): повторный вебхук вернёт ту же оплату, второй не будет."""

    def record(
        self, *, subscription, amount, actor, comment="", transaction_id, raw_response=None
    ) -> Payment:
        if to_tenge(amount) <= 0:
            raise ValueError("Сумма оплаты должна быть больше нуля.")
        payment, created = Payment.objects.get_or_create(
            provider=Payment.Provider.KASPI_PAY,
            provider_transaction_id=f"{subscription.organization_id}:{transaction_id}",
            defaults=dict(
                organization=subscription.organization,
                subscription=subscription,
                amount=to_tenge(amount),
                method=Payment.Method.KASPI_TRANSFER,
                status=Payment.Status.CONFIRMED,
                confirmed_at=timezone.now(),
                provider_raw_response=raw_response or {},
                received_by=actor,
                comment=comment,
            ),
        )
        if created:
            AuditLog.record(
                actor=actor,
                action=AuditLog.Action.CREATE,
                entity=payment,
                after={
                    "amount": str(payment.amount),
                    "method": payment.method,
                    "provider": "kaspi_pay",
                },
            )
        return payment
