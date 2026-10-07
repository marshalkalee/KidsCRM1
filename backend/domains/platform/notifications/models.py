"""
Центр уведомлений сотрудника (ТЗ п. 4.5; TRU-72).

Сами уведомления не хранятся — считаются на лету из живых данных
(sources.py): новая заявка, занятие без отметки, долг. Если хранить их
копией, копия разойдётся с экранами, а критерий приёмки — «счётчики
совпадают с содержимым экранов». Хранится только то, что видел сотрудник:
когда он в последний раз открыл уведомление этого вида.
"""

from django.conf import settings
from django.db import models

from domains.platform.core.models import TenantModel, UUIDPrimaryKeyModel


class NotificationSeen(UUIDPrimaryKeyModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications_seen"
    )
    kind = models.CharField(max_length=40)
    seen_at = models.DateTimeField()
    # Для видов без естественного времени события (дети без абонемента,
    # просроченные долги): «новое» — если стало больше, чем было при просмотре.
    seen_count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "kind"], name="notification_seen_unique_user_kind"
            )
        ]


# --- Центр рассылок родителям (TRU-168, ADR-0010) -------------------------
#
# Контракт: родителю пишет только messaging.notify(). Модели ниже — его
# состояние: согласие, тексты центра, журнал каждой попытки.


class MessageCategory(models.TextChoices):
    # Служебные: абонемент, оплата, отмена занятия. Маркетинг — акции, только
    # по отдельному согласию (ADR-0010, п. 4).
    UTILITY = "utility", "Служебные"
    MARKETING = "marketing", "Рекламные"


class MessagingConsent(TenantModel):
    """Согласие родителя на сообщения. Не путать с Child.consent_given —
    это согласие на обработку ПДн ребёнка. Нет строки — согласия нет."""

    class Status(models.TextChoices):
        OPTED_IN = "opted_in", "Согласен"
        OPTED_OUT = "opted_out", "Отписался"

    class Source(models.TextChoices):
        ADMIN_FORM = "admin_form", "Отметил сотрудник (анкета, договор)"
        PARENT_PORTAL = "parent_portal", "Сам в кабинете"
        UNSUBSCRIBE_LINK = "unsubscribe_link", "Ссылка «отписаться» в письме"
        WHATSAPP_REPLY = "whatsapp_reply", "Ответ «Стоп» в WhatsApp"
        EMAIL_COMPLAINT = "email_complaint", "Жалоба на письмо"

    parent = models.ForeignKey(
        "clients.ParentContact", on_delete=models.CASCADE, related_name="messaging_consents"
    )
    category = models.CharField(max_length=16, choices=MessageCategory.choices)
    status = models.CharField(max_length=16, choices=Status.choices)
    source = models.CharField(max_length=24, choices=Source.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    changed_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "parent", "category"],
                name="messaging_consent_unique_parent_category",
            )
        ]


class MessageTemplate(TenantModel):
    """Свой текст центра для события и канала. Нет строки — текст по
    умолчанию из messaging.events. WhatsApp-тексты утверждает Meta, поэтому
    правится только email (WhatsApp — TRU-169)."""

    event = models.CharField(max_length=40)
    channel = models.CharField(max_length=16)
    language = models.CharField(max_length=5)
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "event", "channel", "language"],
                name="message_template_unique",
            )
        ]


class OutboundMessage(TenantModel):
    """Журнал: одно событие для одного родителя — одна строка (dedup_key),
    даже если задача выполнилась дважды. Отвечает на «что мы написали этой
    семье»: когда, каким каналом, каким текстом, что вышло."""

    class Status(models.TextChoices):
        QUEUED = "queued", "В очереди"
        DEFERRED = "deferred", "Ждёт утра (тихие часы)"
        SENDING = "sending", "Отправляется"
        SENT = "sent", "Отправлено"
        DELIVERED = "delivered", "Доставлено"
        FAILED = "failed", "Не дошло"
        NO_CONSENT = "no_consent", "Нет согласия"
        OPTED_OUT = "opted_out", "Родитель отписался"
        NO_CHANNEL = "no_channel", "Нет канала (нет email, WhatsApp не подключён)"

    parent = models.ForeignKey(
        "clients.ParentContact", on_delete=models.CASCADE, related_name="outbound_messages"
    )
    event = models.CharField(max_length=40)
    category = models.CharField(max_length=16, choices=MessageCategory.choices)
    dedup_key = models.CharField(max_length=200)
    context = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    channel = models.CharField(max_length=16, blank=True)
    recipient = models.CharField(max_length=255, blank=True)
    language = models.CharField(max_length=5, blank=True)
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField(blank=True)
    provider_id = models.CharField(max_length=255, blank=True)
    # Попытки по каналам: [{"channel": "email", "result": "failed", "error": "…"}].
    attempts = models.JSONField(default=list, blank=True)
    error = models.CharField(max_length=500, blank=True)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "dedup_key"], name="outbound_message_unique_dedup"
            )
        ]
        indexes = [
            models.Index(fields=["organization", "parent", "-created_at"]),
            models.Index(fields=["organization", "status", "-created_at"]),
            models.Index(fields=["provider_id"]),
        ]
