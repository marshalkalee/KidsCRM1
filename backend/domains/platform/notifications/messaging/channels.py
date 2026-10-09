"""
Каналы доставки (TRU-168). Сервис перебирает их в порядке из настроек
центра и останавливается на первом, кто отправил. У канала два вопроса:

- recipient(): куда отправлять этому родителю — или None и почему нет
  (нет email, WhatsApp центру не подключён);
- send(): отправить готовый текст, вернуть id у провайдера или бросить
  ChannelError — тогда сервис пробует следующий канал.

Прямые вызовы провайдеров живут только здесь (tests_contract проверяет).
WhatsApp — TRU-169: пока «не подключён» и просто пропускается.
"""

import json
import logging
from email.utils import formataddr

from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone

from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number
from domains.platform.tenants.org_settings import MESSAGING_REPLY_TO, get_org_setting

from .recipients import accounts_for_parent

logger = logging.getLogger(__name__)


class ChannelError(Exception):
    """Канал не смог отправить — пробуем следующий."""


class Channel:
    key = ""
    label = ""

    def recipient(self, parent) -> tuple[str | None, str]:
        raise NotImplementedError

    def send(self, message, *, unsubscribe_url: str) -> str:
        raise NotImplementedError


class EmailChannel(Channel):
    key = "email"
    label = "Email"

    def recipient(self, parent):
        if not parent.email:
            return None, "у родителя нет email"
        return parent.email, ""

    def send(self, message, *, unsubscribe_url):
        organization = message.organization
        reply_to = get_org_setting(organization, MESSAGING_REPLY_TO)
        email = EmailMessage(
            subject=message.subject,
            body=message.body,
            from_email=formataddr((organization.name, settings.MESSAGING_FROM_EMAIL)),
            to=[message.recipient],
            reply_to=[reply_to] if reply_to else None,
            headers={
                # Кнопка «Отписаться» в Gmail и других (RFC 8058).
                "List-Unsubscribe": f"<{unsubscribe_url}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            },
        )
        # По тегу вебхук anymail находит строку журнала при недоставке.
        email.metadata = {"message_id": str(message.id)}
        try:
            email.send(fail_silently=False)
        except Exception as exc:  # noqa: BLE001 — любой отказ провайдера = канал не сработал
            raise ChannelError(f"Почта не приняла письмо: {exc}"[:300]) from exc
        status = getattr(email, "anymail_status", None)
        return (getattr(status, "message_id", None) or "") if status else ""


class PushChannel(Channel):
    """Web Push в кабинете родителя (TRU-172): все устройства, где родитель
    включил напоминания. Бесплатно — поэтому первым в порядке каналов.
    Провайдер ответил 404/410 — подписки больше нет, строка удаляется.
    Ни одно устройство не приняло — ChannelError, сервис пробует WhatsApp
    и email: дублей нет, потому что после первого принятого перебор
    останавливается."""

    key = "push"
    label = "Push в кабинете"

    @property
    def reason(self):
        if not (settings.WEBPUSH_VAPID_PUBLIC_KEY and settings.WEBPUSH_VAPID_PRIVATE_KEY):
            return "push не настроен на сервере (ключи VAPID)"
        return ""

    def subscriptions(self, parent):
        from domains.people.portal.models import PushSubscription

        return PushSubscription.objects.filter(account__in=accounts_for_parent(parent))

    def recipient(self, parent):
        if self.reason:
            return None, self.reason
        count = self.subscriptions(parent).count()
        if not count:
            return None, "родитель не включил напоминания в кабинете"
        return f"{count} устр.", ""

    def send(self, message, *, unsubscribe_url):
        from pywebpush import WebPushException, webpush

        from .events import EVENTS

        event = EVENTS.get(message.event)
        payload = json.dumps(
            {
                "title": message.subject,
                "body": message.body,
                "url": event.link if event else "/parent",
                "tag": message.event,
            },
            ensure_ascii=False,
        )
        delivered, errors = 0, []
        for subscription in self.subscriptions(message.parent):
            try:
                webpush(
                    subscription_info={
                        "endpoint": subscription.endpoint,
                        "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                    },
                    data=payload,
                    vapid_private_key=settings.WEBPUSH_VAPID_PRIVATE_KEY,
                    vapid_claims={"sub": settings.WEBPUSH_CONTACT},
                    ttl=24 * 3600,
                )
            except WebPushException as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status in (404, 410):
                    # Родитель удалил кабинет или запретил уведомления в браузере.
                    subscription.delete()
                else:
                    errors.append(f"{status or ''} {exc}"[:200])
                continue
            delivered += 1
            subscription.last_sent_at = timezone.now()
            subscription.save(update_fields=["last_sent_at"])
        if not delivered:
            raise ChannelError(
                "; ".join(errors) or "подписки устройств больше не действуют — удалены"
            )
        return f"push:{delivered}"


class WhatsAppChannel(Channel):
    key = "whatsapp"
    label = "WhatsApp"

    @property
    def reason(self):
        return ""

    def recipient(self, parent):
        from ..models import WhatsAppConnection
        from .whatsapp import connection_for

        connection = connection_for(parent.organization)
        if not connection or connection.status != WhatsAppConnection.Status.CONNECTED:
            return None, "WhatsApp центру не подключён"
        raw = parent.whatsapp or parent.phones.values_list("number", flat=True).first()
        if not raw:
            return None, "у родителя нет номера WhatsApp"
        try:
            return normalize_phone_number(raw), ""
        except InvalidPhoneNumberError:
            return None, "номер WhatsApp имеет неверный формат"

    def send(self, message, *, unsubscribe_url):
        from .whatsapp import WhatsAppError, send_free_text, send_template

        try:
            if message.event == "whatsapp_reply":
                return send_free_text(message)
            return send_template(message)
        except WhatsAppError as exc:
            raise ChannelError(str(exc)) from exc


class NotConnectedChannel(Channel):
    """Канал из настроек, которого ещё нет в системе: пропускается."""

    def __init__(self, key, label, reason):
        self.key, self.label, self.reason = key, label, reason

    def recipient(self, parent):
        return None, self.reason

    def send(self, message, *, unsubscribe_url):
        raise ChannelError(self.reason)


CHANNELS = {
    "email": EmailChannel(),
    "whatsapp": WhatsAppChannel(),
    "push": PushChannel(),
}
