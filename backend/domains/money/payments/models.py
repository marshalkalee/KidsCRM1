from django.db import models  # noqa: F401

"""Оплата (ТЗ п. 3.1, 4.4). Способ оплаты — открытый список, не намертво
зашитый enum: Kaspi в MVP фиксируется вручную, но модель должна пережить
добавление платёжного шлюза без переделки (ТЗ п. 4.4)."""

from django.conf import settings

from domains.platform.core.models import TenantModel


class Payment(TenantModel):
    class Method(models.TextChoices):
        KASPI_TRANSFER = "kaspi_transfer", "Kaspi-перевод"
        CASH = "cash", "Наличные"
        CARD = "card", "Карта"
        OTHER = "other", "Другое"

    subscription = models.ForeignKey(
        "subscriptions.Subscription", on_delete=models.PROTECT, related_name="payments",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=0)
    method = models.CharField(max_length=20, choices=Method.choices)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments_received")
    comment = models.CharField(max_length=255, blank=True)
    paid_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-paid_at"]

    def __str__(self) -> str:
        return f"{self.subscription} — {self.amount} ({self.get_method_display()})"