"""
Evolution API — номер WhatsApp центра или филиала по QR-коду (как WhatsApp Web).

Сервер Evolution (github.com/evolution-foundation/evolution-api, образ
evoapicloud/evolution-api) стоит рядом с CRM в docker-compose и наружу не
открыт: CRM ходит к нему по внутреннему адресу EVOLUTION_API_URL с общим
ключом EVOLUTION_API_KEY. Одно подключение (instance) = один номер.

Что приходит обратно — вебхук на /messaging/whatsapp/evolution/<секрет>/:
- connection.update — номер подключился или отвалился;
- messages.upsert — входящее сообщение (или своё, отправленное с телефона);
- messages.update — доставлено / прочитано.

Форматы сверены с исходниками Evolution 2.3.7.
"""

import base64
import json
import logging
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number

from ..models import OutboundMessage, WhatsAppConnection

logger = logging.getLogger(__name__)

# MESSAGES_DELETE — собеседник удалил своё сообщение у всех.
WEBHOOK_EVENTS = ["CONNECTION_UPDATE", "MESSAGES_UPSERT", "MESSAGES_UPDATE", "MESSAGES_DELETE"]

# Статусы доставки Evolution → журнал. Назад статус не откатываем.
DELIVERY_STATUS = {
    "SERVER_ACK": OutboundMessage.Status.SENT,
    "DELIVERY_ACK": OutboundMessage.Status.DELIVERED,
    "READ": OutboundMessage.Status.READ,
    "PLAYED": OutboundMessage.Status.READ,
}
STATUS_RANK = {
    OutboundMessage.Status.SENT: 1,
    OutboundMessage.Status.DELIVERED: 2,
    OutboundMessage.Status.READ: 3,
}

# Тип сообщения Evolution → тип входящего в CRM.
MESSAGE_KINDS = {
    "conversation": "text",
    "extendedTextMessage": "text",
    "imageMessage": "image",
    "videoMessage": "video",
    # Видеосообщение-«кружочек».
    "ptvMessage": "video_note",
    "audioMessage": "audio",
    "documentMessage": "document",
    "documentWithCaptionMessage": "document",
    "stickerMessage": "sticker",
    "locationMessage": "location",
    "liveLocationMessage": "location",
    "contactMessage": "contacts",
    "contactsArrayMessage": "contacts",
}
# Служебное, не сообщение родителя: реакции, удаления, правки, опросы.
IGNORED_KINDS = {
    "reactionMessage",
    "protocolMessage",
    "editedMessage",
    "pollUpdateMessage",
    "senderKeyDistributionMessage",
    "messageContextInfo",
    "unknown",
}


class EvolutionError(Exception):
    pass


class SendLater(EvolutionError):
    """Очередь номера занята дольше EVOLUTION_MAX_WAIT — отправить позже."""

    def __init__(self, retry_at):
        super().__init__("Очередь отправки номера занята")
        self.retry_at = retry_at


def is_configured() -> bool:
    return bool(settings.EVOLUTION_API_URL and settings.EVOLUTION_API_KEY)


def _request(method, path, payload=None, timeout=None):
    if not is_configured():
        raise EvolutionError("Подключение по QR-коду не настроено на сервере.")
    url = f"{settings.EVOLUTION_API_URL.rstrip('/')}/{path.lstrip('/')}"
    request = urllib.request.Request(
        url,
        method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"apikey": settings.EVOLUTION_API_KEY, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(
            request, timeout=timeout or settings.EVOLUTION_HTTP_TIMEOUT
        ) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise EvolutionError(_error_text(exc.code, detail)) from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise EvolutionError(f"Сервер WhatsApp недоступен: {exc}"[:500]) from exc


def _error_text(code, detail):
    try:
        body = json.loads(detail)
    except ValueError:
        body = {}
    response = body.get("response") if isinstance(body, dict) else None
    messages = response.get("message") if isinstance(response, dict) else None
    # Номера нет в WhatsApp: [{"exists": false, "jid": "…", "number": "…"}].
    if isinstance(messages, list) and any(
        isinstance(item, dict) and item.get("exists") is False for item in messages
    ):
        return "У этого номера нет WhatsApp"
    if code == 404:
        return "Подключение не найдено на сервере WhatsApp — подключите номер заново"
    if code == 401:
        return "Сервер WhatsApp не принял ключ доступа (EVOLUTION_API_KEY)"
    text = messages if isinstance(messages, str) else json.dumps(messages or detail)
    return f"Ошибка сервера WhatsApp ({code}): {text}"[:500]


def _webhook_config(connection) -> dict:
    # base64 — Evolution кладёт в событие сам файл (фото, голосовое, документ).
    return {
        "enabled": True,
        "url": webhook_url(connection),
        "byEvents": False,
        "base64": True,
        "events": WEBHOOK_EVENTS,
    }


def ensure_webhook(connection) -> None:
    """Обновить настройки вебхука на сервере Evolution (адрес, события, файлы)."""
    _request(
        "POST",
        f"webhook/set/{urllib.parse.quote(connection.instance_name)}",
        {"webhook": _webhook_config(connection)},
    )


def webhook_url(connection) -> str:
    base = (settings.EVOLUTION_WEBHOOK_BASE_URL or settings.PUBLIC_BASE_URL).rstrip("/")
    return f"{base}/api/v1/messaging/whatsapp/evolution/{connection.webhook_secret}/"


def _digits(phone: str) -> str:
    return "".join(ch for ch in phone or "" if ch.isdigit())


def phone_from_jid(jid: str) -> str:
    """'77001234567@s.whatsapp.net' → '+77001234567'; группы и скрытые номера — ''."""
    if not jid or not jid.endswith("@s.whatsapp.net"):
        return ""
    try:
        return normalize_phone_number("+" + jid.split("@")[0].split(":")[0])
    except InvalidPhoneNumberError:
        return ""


# --- Подключение номера ------------------------------------------------------


def _qr(payload) -> dict:
    qrcode = payload.get("qrcode") if isinstance(payload.get("qrcode"), dict) else payload
    return {"base64": qrcode.get("base64") or "", "pairing_code": qrcode.get("pairingCode") or ""}


def create_instance(connection) -> dict:
    """Создать подключение на сервере Evolution и вернуть первый QR-код."""
    if not connection.instance_name:
        connection.instance_name = (
            f"kidscrm-{connection.organization_id.hex[:8]}-{secrets.token_hex(4)}"
        )
    if not connection.webhook_secret:
        connection.webhook_secret = secrets.token_urlsafe(32)
    payload = _request(
        "POST",
        "instance/create",
        {
            "instanceName": connection.instance_name,
            "integration": "WHATSAPP-BAILEYS",
            "qrcode": True,
            # Группы — не родители: иначе каждое сообщение группы стало бы заявкой.
            "groupsIgnore": True,
            "alwaysOnline": False,
            "readMessages": False,
            "readStatus": False,
            "syncFullHistory": False,
            "rejectCall": False,
            "webhook": _webhook_config(connection),
        },
    )
    return _qr(payload)


def fetch_qr(connection) -> dict:
    """Свежий QR-код (старый живёт меньше минуты) или state=open, если уже подключён."""
    payload = _request("GET", f"instance/connect/{urllib.parse.quote(connection.instance_name)}")
    instance = payload.get("instance") if isinstance(payload.get("instance"), dict) else {}
    if instance.get("state") == "open":
        return {"state": "open", "base64": "", "pairing_code": ""}
    return {"state": "connecting", **_qr(payload)}


def instance_owner(connection) -> str:
    """Номер, который отсканировал QR: '77001234567@s.whatsapp.net' или ''."""
    payload = _request(
        "GET",
        f"instance/fetchInstances?instanceName={urllib.parse.quote(connection.instance_name)}",
    )
    rows = payload if isinstance(payload, list) else [payload]
    for row in rows:
        if isinstance(row, dict) and row.get("ownerJid"):
            return row["ownerJid"]
    return ""


def connection_state(connection) -> str:
    """open / connecting / close."""
    payload = _request(
        "GET", f"instance/connectionState/{urllib.parse.quote(connection.instance_name)}"
    )
    instance = payload.get("instance") if isinstance(payload.get("instance"), dict) else payload
    return instance.get("state") or "close"


def delete_instance(connection) -> None:
    """Выйти из WhatsApp на телефоне центра и удалить подключение с сервера."""
    if not connection.instance_name:
        return
    name = urllib.parse.quote(connection.instance_name)
    for path in (f"instance/logout/{name}", f"instance/delete/{name}"):
        try:
            _request("DELETE", path)
        except EvolutionError as exc:
            # Уже вышли или удалено — не мешает отключению в CRM.
            logger.info("Evolution %s: %s", path, exc)


def apply_state(connection, state, *, wuid="", reason="") -> bool:
    """Записать состояние номера. True — номер только что отвалился."""
    was_connected = connection.status == WhatsAppConnection.Status.CONNECTED
    fields = ["status", "last_error", "updated_at"]
    if state == "open":
        connection.status = WhatsAppConnection.Status.CONNECTED
        connection.last_error = ""
        connection.verified_at = timezone.now()
        fields.append("verified_at")
        if not connection.connected_at:
            connection.connected_at = connection.verified_at
            fields.append("connected_at")
        phone = phone_from_jid(wuid)
        if phone:
            connection.business_phone = phone
            fields.append("business_phone")
    elif state == "connecting":
        if was_connected:
            return False  # переподключение на секунду — не тревожим
        connection.status = WhatsAppConnection.Status.CONNECTING
    else:
        connection.status = WhatsAppConnection.Status.DISCONNECTED
        connection.last_error = reason or (
            "Номер отключился от WhatsApp. Подключите его заново по QR-коду."
            if was_connected
            else "QR-код не отсканирован. Подключите номер заново."
        )
    connection.save(update_fields=fields)
    return was_connected and connection.status != WhatsAppConnection.Status.CONNECTED


# --- Отправка ----------------------------------------------------------------


def _wait_turn(connection):
    """Не чаще одного сообщения в EVOLUTION_SEND_INTERVAL секунд с номера:
    сотня напоминаний подряд в 9:00 похожа на спам и ведёт к блокировке."""
    interval = timedelta(seconds=settings.EVOLUTION_SEND_INTERVAL)
    with transaction.atomic():
        row = WhatsAppConnection.objects.select_for_update().get(pk=connection.pk)
        now = timezone.now()
        slot = max(now, row.next_send_at or now)
        wait = (slot - now).total_seconds()
        if wait > settings.EVOLUTION_MAX_WAIT:
            # Место не занимаем: вернёмся, когда очередь подойдёт.
            raise SendLater(slot - timedelta(seconds=settings.EVOLUTION_MAX_WAIT / 2))
        row.next_send_at = slot + interval
        row.save(update_fields=["next_send_at"])
    if wait > 0:
        time.sleep(wait)


def send_text(connection, phone, text) -> str:
    """Отправить текст, вернуть id сообщения WhatsApp."""
    if connection.status != WhatsAppConnection.Status.CONNECTED:
        raise EvolutionError("Номер WhatsApp не подключён")
    _wait_turn(connection)
    payload = _request(
        "POST",
        f"message/sendText/{urllib.parse.quote(connection.instance_name)}",
        {
            "number": _digits(phone),
            "text": text,
            # «Печатает…» перед отправкой — как живой администратор.
            "delay": 1200,
            "linkPreview": False,
        },
        # Evolution держит запрос, пока «печатает».
        timeout=settings.EVOLUTION_HTTP_TIMEOUT + 5,
    )
    key = payload.get("key") if isinstance(payload.get("key"), dict) else {}
    if not key.get("id"):
        raise EvolutionError("Сервер WhatsApp не вернул ID сообщения")
    return key["id"]


def delete_for_everyone(connection, phone, provider_id) -> None:
    """Удалить наше сообщение у всех в WhatsApp («Это сообщение удалено»)."""
    if connection.status != WhatsAppConnection.Status.CONNECTED:
        raise EvolutionError("Номер WhatsApp не подключён")
    _request(
        "DELETE",
        f"chat/deleteMessageForEveryone/{urllib.parse.quote(connection.instance_name)}",
        {"id": provider_id, "fromMe": True, "remoteJid": f"{_digits(phone)}@s.whatsapp.net"},
    )


# --- Вебхук ------------------------------------------------------------------


def _content(message: dict) -> tuple[str, str, dict]:
    """(тип Evolution, текст, вложение) из поля data.message."""
    if not isinstance(message, dict):
        return "unknown", "", {}
    if message.get("conversation"):
        return "conversation", str(message["conversation"]).strip(), {}
    if isinstance(message.get("extendedTextMessage"), dict):
        return "conversation", str(message["extendedTextMessage"].get("text", "")).strip(), {}
    wrapped = message.get("documentWithCaptionMessage")
    if isinstance(wrapped, dict) and isinstance(wrapped.get("message"), dict):
        message = wrapped["message"]
    for kind in MESSAGE_KINDS:
        value = message.get(kind)
        if not isinstance(value, dict):
            continue
        media = {
            "mime_type": value.get("mimetype") or "",
            "filename": value.get("fileName") or value.get("title") or "",
            "caption": value.get("caption") or "",
        }
        media = {key: item for key, item in media.items() if item}
        text = value.get("caption") or value.get("fileName") or value.get("displayName") or ""
        return kind, str(text).strip(), media
    keys = [key for key in message if key not in ("messageContextInfo",)]
    return (keys[0] if keys else "unknown"), "", {}


def parse_incoming(data: dict) -> dict | None:
    """data события messages.upsert → поля входящего или None (не для CRM)."""
    key = data.get("key") if isinstance(data.get("key"), dict) else {}
    jid = key.get("remoteJid") or ""
    if key.get("fromMe") or not key.get("id"):
        return None
    if jid.endswith(("@g.us", "@broadcast", "@newsletter")) or jid == "status@broadcast":
        return None
    kind, text, media = _content(data.get("message"))
    if kind in IGNORED_KINDS or data.get("messageType") in IGNORED_KINDS:
        return None
    # Новые аккаунты WhatsApp прячут номер (@lid); Evolution подставляет
    # настоящий номер в remoteJidAlt, когда он известен.
    phone = phone_from_jid(jid) or phone_from_jid(key.get("remoteJidAlt") or "")
    timestamp = data.get("messageTimestamp")
    try:
        sent_at = datetime.fromtimestamp(int(timestamp), tz=UTC) if timestamp else timezone.now()
    except (TypeError, ValueError, OverflowError):
        sent_at = timezone.now()
    return {
        "provider_message_id": key["id"],
        "sender_phone": phone,
        "sender_name": str(data.get("pushName") or "")[:255],
        "message_type": MESSAGE_KINDS.get(kind, kind)[:24],
        "text": text,
        "media": media,
        "provider_sent_at": sent_at,
        "media_file": data.get("_media_path") or "",
        "raw_payload": {
            "key": key,
            "messageType": data.get("messageType"),
            "pushName": data.get("pushName"),
        },
    }


# --- Файлы ---------------------------------------------------------------------

INCOMING_MEDIA_MAX_BYTES = 25 * 1024 * 1024
MEDIA_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/aac": "aac",
    "audio/amr": "amr",
    "video/mp4": "mp4",
    "application/pdf": "pdf",
}
MEDIA_NAMES = {
    "imageMessage": "фото",
    "audioMessage": "голосовое",
    "videoMessage": "видео",
    "ptvMessage": "видеосообщение",
    "stickerMessage": "стикер",
    "documentMessage": "документ",
}


def save_incoming_media(organization_id, data: dict) -> str:
    """Достать файл из события (base64), сохранить; вернуть путь или ''.
    Вызывается в вебхуке до очереди — в Celery идёт путь, а не мегабайты."""
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage

    from domains.platform.core.attachments import upload_path

    message = data.get("message") if isinstance(data.get("message"), dict) else {}
    encoded = message.pop("base64", None)
    if not encoded or not isinstance(encoded, str):
        return ""
    if len(encoded) * 3 // 4 > INCOMING_MEDIA_MAX_BYTES:
        return ""
    try:
        content = base64.b64decode(encoded, validate=False)
    except (ValueError, TypeError):
        return ""
    wrapped = message.get("documentWithCaptionMessage")
    if isinstance(wrapped, dict) and isinstance(wrapped.get("message"), dict):
        message = wrapped["message"]
    kind = next((key for key in MEDIA_NAMES if isinstance(message.get(key), dict)), "")
    info = message.get(kind) or {}
    mimetype = str(info.get("mimetype") or "").split(";")[0].strip()
    filename = str(info.get("fileName") or "").strip()
    if not filename:
        filename = f"{MEDIA_NAMES.get(kind, 'файл')}.{MEDIA_EXTENSIONS.get(mimetype, 'bin')}"
    path = upload_path("whatsapp", organization_id, filename.replace("/", "_")[:150])
    return default_storage.save(path, ContentFile(content))


def _media_kind(content_type: str, name: str) -> str:
    from domains.platform.core.attachments import AUDIO_EXTENSIONS, IMAGE_EXTENSIONS, extension

    ext = extension(name)
    if content_type.startswith("audio/") or ext in AUDIO_EXTENSIONS:
        return "audio"
    if ext in IMAGE_EXTENSIONS - {"heic"} or content_type in (
        "image/jpeg",
        "image/png",
        "image/webp",
    ):
        return "image"
    if content_type.startswith("video/") or ext in {"mp4", "3gp"}:
        return "video"
    return "document"


def send_media(connection, phone, message) -> str:
    """Отправить файл сообщения (body — подпись). Аудио уходит голосовым."""
    if connection.status != WhatsAppConnection.Status.CONNECTED:
        raise EvolutionError("Номер WhatsApp не подключён")
    with message.media_file.open("rb") as handle:
        encoded = base64.b64encode(handle.read()).decode()
    kind = _media_kind(message.media_type, message.media_name)
    name = urllib.parse.quote(connection.instance_name)
    _wait_turn(connection)
    if kind == "audio":
        path, body = (
            f"message/sendWhatsAppAudio/{name}",
            {"number": _digits(phone), "audio": encoded},
        )
    else:
        path = f"message/sendMedia/{name}"
        body = {
            "number": _digits(phone),
            "mediatype": kind,
            "mimetype": message.media_type or "application/octet-stream",
            "caption": message.body,
            "fileName": message.media_name,
            "media": encoded,
        }
    # Большие файлы и перекодирование голосового — дольше обычного текста.
    payload = _request("POST", path, body, timeout=settings.EVOLUTION_HTTP_TIMEOUT + 60)
    key = payload.get("key") if isinstance(payload.get("key"), dict) else {}
    if not key.get("id"):
        raise EvolutionError("Сервер WhatsApp не вернул ID сообщения")
    return key["id"]


def apply_delivery(connection, data: dict) -> bool:
    """messages.update: доставлено / прочитано / ошибка для нашего сообщения."""
    if not data.get("fromMe"):
        return False
    provider_id = data.get("keyId") or ""
    message = (
        OutboundMessage.objects.for_tenant(connection.organization)
        .filter(provider_id=provider_id)
        .first()
        if provider_id
        else None
    )
    if message is None:
        return False
    state = data.get("status")
    if state == "ERROR":
        message.status = OutboundMessage.Status.FAILED
        message.error = "WhatsApp не доставил сообщение"
    else:
        new_status = DELIVERY_STATUS.get(state)
        if not new_status or STATUS_RANK.get(new_status, 0) <= STATUS_RANK.get(message.status, 0):
            return False
        message.status = new_status
        message.error = ""
    message.save(update_fields=["status", "error", "updated_at"])
    return True
