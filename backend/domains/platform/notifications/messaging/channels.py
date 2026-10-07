"""
Каналы доставки (TRU-168). Сервис перебирает их в порядке из настроек
центра и останавливается на первом, кто отправил. У канала два вопроса:

- recipient(): куда отправлять этому родителю — или None и почему нет
  (нет email, WhatsApp центру не подключён);
- send(): отправить готовый текст, вернуть id у провайдера или бросить
  ChannelError — тогда сервис пробует следующий канал.

Прямые вызовы провайдеров живут только здесь (tests_contract проверяет).
WhatsApp — TRU-169, push в кабинете — TRU-172: пока они «не подключены» и
просто пропускаются.
"""

from email.utils import formataddr

from django.conf import settings
from django.core.mail import EmailMessage

from domains.platform.tenants.org_settings import MESSAGING_REPLY_TO, get_org_setting


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
    "whatsapp": NotConnectedChannel("whatsapp", "WhatsApp", "WhatsApp центру не подключён"),
    "push": NotConnectedChannel("push", "Push в кабинете", "push в кабинете ещё не работает"),
}
