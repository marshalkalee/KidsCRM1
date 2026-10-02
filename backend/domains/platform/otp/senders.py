"""
Отправка одноразового кода входа родителю (ADR-0007, TRU-134).

Логика входа (TRU-135) знает только send_code(phone, code): какой канал и
провайдер доставит код — решает настройка OTP_CHANNELS, список по порядку:
первый не смог — пробуем следующий. Сменить провайдера = поменять строку
в .env, код входа не трогается.

Каналы:
- console  — код в лог, ничего не отправляется (разработка, тесты, стенд);
- telegram — Telegram Gateway (core.telegram.org/gateway), ~$0.01 за код,
             только если у номера есть Telegram; не дошёл — деньги вернут;
- sms      — Mobizon (mobizon.kz), казахстанский агрегатор, все операторы РК.

WhatsApp не реализован: нужен договор с BSP и верификация бизнеса в Meta
(ADR-0007, «Открыто»). Новый канал — класс с send() и строка в CHANNELS.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10


class SendFailed(Exception):
    """Канал не доставил код — пробуем следующий. Текст — для лога, не родителю."""


def message_text(code: str) -> str:
    # Название центра в SMS не пишем: по номеру нельзя узнать, куда ходит
    # ребёнок, даже если телефон в чужих руках (TRU-135, неразглашение).
    return f"KidsCRM: код входа {code}. Никому его не сообщайте."


def _digits(phone: str) -> str:
    return "".join(ch for ch in phone if ch.isdigit())


def _masked(phone: str) -> str:
    digits = _digits(phone)
    return f"+{digits[:4]}***{digits[-2:]}" if len(digits) > 6 else "***"


def _post(url, *, data=None, json_body=None, headers=None) -> dict:
    body = None
    headers = dict(headers or {})
    if json_body is not None:
        body = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif data is not None:
        body = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode() or "{}")
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise SendFailed(f"{url}: {exc}") from exc


class ConsoleSender:
    name = "console"

    def send(self, phone: str, code: str) -> None:
        logger.warning("OTP для %s: %s (канал console — код не отправлялся)", _masked(phone), code)


class TelegramGatewaySender:
    """https://core.telegram.org/gateway/api — sendVerificationMessage."""

    name = "telegram"
    URL = "https://gatewayapi.telegram.org/sendVerificationMessage"

    def send(self, phone: str, code: str) -> None:
        token = settings.OTP_TELEGRAM_TOKEN
        if not token:
            raise SendFailed("не задан OTP_TELEGRAM_TOKEN")
        data = _post(
            self.URL,
            json_body={
                "phone_number": f"+{_digits(phone)}",
                "code": code,
                "ttl": settings.OTP_CODE_TTL_SECONDS,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        if not data.get("ok"):
            # PHONE_NUMBER_NOT_FOUND и т.п. — у номера нет Telegram: в SMS.
            raise SendFailed(f"telegram: {data.get('error', 'unknown error')}")


class MobizonSmsSender:
    """https://mobizon.kz/help/api-docs/message — sendSmsMessage."""

    name = "sms"
    URL = "https://api.mobizon.kz/service/message/sendSmsMessage"

    def send(self, phone: str, code: str) -> None:
        api_key = settings.OTP_MOBIZON_API_KEY
        if not api_key:
            raise SendFailed("не задан OTP_MOBIZON_API_KEY")
        payload = {
            "recipient": _digits(phone),
            "text": message_text(code),
            "apiKey": api_key,
            "api": "v1",
            "output": "json",
            # Код живёт минуты — доставка через час уже никому не нужна.
            "params[validity]": 60,
        }
        if settings.OTP_MOBIZON_SENDER:
            payload["from"] = settings.OTP_MOBIZON_SENDER
        data = _post(self.URL, data=payload)
        if data.get("code") != 0:
            raise SendFailed(f"mobizon: code={data.get('code')} {data.get('message', '')}")


CHANNELS = {
    sender.name: sender for sender in (ConsoleSender, TelegramGatewaySender, MobizonSmsSender)
}


def configured_channels() -> list[str]:
    names = [n.strip() for n in settings.OTP_CHANNELS.split(",") if n.strip()]
    unknown = [n for n in names if n not in CHANNELS]
    if unknown:
        raise ValueError(f"Неизвестные каналы OTP: {', '.join(unknown)}")
    return names or ["console"]


def send_code(phone: str, code: str) -> str | None:
    """Доставить код первым сработавшим каналом. Возвращает имя канала или
    None, если не сработал ни один (вход скажет «попробуйте позже»)."""
    for name in configured_channels():
        try:
            CHANNELS[name]().send(phone, code)
        except SendFailed as exc:
            logger.warning("OTP %s: канал %s не доставил код: %s", _masked(phone), name, exc)
            continue
        return name
    logger.error("OTP %s: код не отправлен ни одним каналом", _masked(phone))
    return None
