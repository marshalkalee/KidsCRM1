"""Вебхуки почтового провайдера через anymail: доставлено, не дошло, жалоба."""

from anymail.signals import tracking
from django.dispatch import receiver

from .service import on_email_event


@receiver(tracking)
def handle_email_tracking(sender, event, esp_name, **kwargs):
    on_email_event(
        event.message_id, event.event_type, event.description or event.reject_reason or ""
    )
