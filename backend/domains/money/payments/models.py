"""Оплата (ТЗ п. 3.1, 4.4). Способ оплаты — открытый список, не намертво
зашитый enum: Kaspi в MVP фиксируется вручную, но модель должна пережить
добавление платёжного шлюза без переделки (ТЗ п. 4.4)."""

from django.conf import settings
from django.db import models

from domains.platform.core.models import TenantModel


class Payment(TenantModel):
    class Method(models.TextChoices):
        KASPI_TRANSFER = "kaspi_transfer", "Kaspi-перевод"
        CASH = "cash", "Наличные"
        CARD = "card", "Карта"
        OTHER = "other", "Другое"

    class Provider(models.TextChoices):
        MANUAL = "manual", "Ручная фиксация"
        # Будущие значения (например KASPI_GATEWAY) добавляются без миграции
        # модели — TextChoices не меняет схему таблицы (ТЗ п. 4.4, ADR-003).

    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает"
        CONFIRMED = "confirmed", "Подтверждён"
        REJECTED = "rejected", "Отклонён"
        REFUNDED = "refunded", "Возвращён"

    subscription = models.ForeignKey(
        "subscriptions.Subscription",
        on_delete=models.PROTECT,
        related_name="payments",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=0)
    method = models.CharField(max_length=20, choices=Method.choices)
    provider = models.CharField(max_length=20, choices=Provider.choices, default=Provider.MANUAL)
    provider_transaction_id = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    provider_raw_response = models.JSONField(default=dict, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payments_received",
    )
    comment = models.CharField(max_length=255, blank=True)
    cancelled_reason = models.CharField(max_length=255, blank=True)
    paid_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-paid_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider_transaction_id"],
                name="payment_unique_provider_transaction_id",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.subscription} — {self.amount} ({self.get_method_display()})"
