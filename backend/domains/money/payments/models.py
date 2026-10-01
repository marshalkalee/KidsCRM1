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
        # Оплата по счёту, выставленному из CRM (PaymentRequest): деньги
        # пришли удалённо через Kaspi — подтвердил шлюз или администратор.
        KASPI_PAY = "kaspi_pay", "Счёт Kaspi"

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


class PaymentRequest(TenantModel):
    """
    Счёт на удалённую оплату через Kaspi: родитель платит из дома, не у
    стойки. Пока счёт не оплачен, это не оплата — долг не меняется. Когда
    деньги пришли, создаётся обычная подтверждённая Payment (provider
    KASPI_PAY), и счёт ссылается на неё.

    Два канала:
    - LINK — CRM готовит сообщение родителю с суммой и реквизитами Kaspi
      центра (ссылка Kaspi Pay или номер), администратор отправляет его в
      WhatsApp и сам подтверждает, когда увидел поступление. Работает без
      договора с Kaspi.
    - GATEWAY — счёт уходит в Kaspi по API на телефон родителя, оплата
      подтверждается сама (вебхук/опрос статуса). Нужен договор с Kaspi,
      см. payments/kaspi.py.
    """

    class Channel(models.TextChoices):
        LINK = "link", "Сообщение со ссылкой"
        GATEWAY = "gateway", "Счёт в Kaspi"

    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает оплаты"
        PAID = "paid", "Оплачен"
        CANCELLED = "cancelled", "Отменён"
        EXPIRED = "expired", "Истёк"
        FAILED = "failed", "Не выставлен"

    subscription = models.ForeignKey(
        "subscriptions.Subscription",
        on_delete=models.PROTECT,
        related_name="payment_requests",
    )
    parent_contact = models.ForeignKey(
        "clients.ParentContact",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_requests",
    )
    phone = models.CharField(max_length=20)
    amount = models.DecimalField(max_digits=12, decimal_places=0)
    channel = models.CharField(max_length=10, choices=Channel.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    message = models.TextField(blank=True)
    pay_url = models.URLField(max_length=500, blank=True)
    # Номер счёта у Kaspi (канал GATEWAY) — по нему приходит вебхук.
    external_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    provider_raw_response = models.JSONField(default=dict, blank=True)
    idempotency_key = models.UUIDField(null=True, blank=True)
    payment = models.OneToOneField(
        Payment,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="request",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payment_requests_created",
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="payment_request_unique_idempotency_key",
            ),
        ]
        indexes = [models.Index(fields=["organization", "status"])]

    def __str__(self) -> str:
        return f"Счёт {self.amount} — {self.subscription} ({self.get_status_display()})"
