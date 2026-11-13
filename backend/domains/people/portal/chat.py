"""
Чат с центром в кабинете родителя — та же переписка, что WhatsApp.

Родитель видит свои сообщения (из WhatsApp и из кабинета) и ответы центра.
Написал в кабинете — сообщение попадает в CRM как входящее: в чат карточки,
всплывающее окно и колокольчик, с пометкой «из кабинета». Сотрудник
отвечает из CRM — ответ уходит родителю в WhatsApp и виден здесь же.
"""

import uuid
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number

from . import access

PORTAL_MESSAGE_TYPE = "portal"
THREAD_LIMIT = 200
# Защита от случайной «очереди» одинаковых сообщений и злоупотреблений.
RATE_LIMIT = 10
RATE_WINDOW = timedelta(minutes=1)


class ChatError(Exception):
    pass


def _phone(phone):
    try:
        return normalize_phone_number(phone)
    except InvalidPhoneNumberError:
        return phone


def _contacts(phone, child):
    return access.contacts_for_phone(phone).filter(organization=child.organization)


def _queries(phone, child):
    from domains.platform.notifications.messaging.views import THREAD_OUT_STATUSES
    from domains.platform.notifications.models import InboundWhatsAppMessage, OutboundMessage

    contacts = list(_contacts(phone, child))
    inbound = InboundWhatsAppMessage.objects.for_tenant(child.organization).filter(
        Q(parent__in=contacts) | Q(sender_phone=_phone(phone))
    )
    outbound = OutboundMessage.objects.for_tenant(child.organization).filter(
        parent__in=contacts, channel="whatsapp", status__in=THREAD_OUT_STATUSES
    )
    return contacts, inbound, outbound


def _media(child, direction, message_id, field_file, name, content_type, message_type=""):
    from domains.platform.notifications.messaging.evolution import _media_kind

    if not field_file:
        return None
    filename = name or field_file.name.rsplit("/", 1)[-1]
    kind = "video_note" if message_type == "video_note" else _media_kind(content_type, filename)
    return {
        "url": f"children/{child.id}/chat/media/{direction}/{message_id}/",
        "name": filename,
        "content_type": content_type,
        "kind": kind,
    }


# Удалить у всех — только своё сообщение из кабинета и недавнее (как WhatsApp).
REVOKE_WINDOW = timedelta(hours=48)


def _can_revoke(message) -> bool:
    return bool(
        message.message_type == PORTAL_MESSAGE_TYPE
        and not message.revoked_at
        and message.created_at >= timezone.now() - REVOKE_WINDOW
    )


def thread(phone, child) -> dict:
    """Переписка с центром: «me» — родитель, «center» — центр. Удалённое
    родителем «у себя» здесь не показываем (в CRM оно остаётся)."""
    _contacts_, inbound, outbound = _queries(phone, child)
    inbound = inbound.filter(parent_hidden_at__isnull=True)
    outbound = outbound.filter(parent_hidden_at__isnull=True)
    items = [
        {
            "id": str(m.id),
            "direction": "me",
            "at": m.provider_sent_at or m.created_at,
            "text": ""
            if m.revoked_at
            else (m.media.get("caption") or "")
            if m.media_file
            else m.text,
            "revoked": bool(m.revoked_at),
            "media": None
            if m.revoked_at
            else _media(
                child,
                "in",
                m.id,
                m.media_file,
                m.media.get("filename") or "",
                m.media.get("mime_type") or "",
                m.message_type,
            ),
            "can_revoke": _can_revoke(m),
        }
        for m in inbound.order_by("-created_at")[:THREAD_LIMIT]
    ] + [
        {
            "id": str(m.id),
            "direction": "center",
            "at": m.sent_at or m.created_at,
            "text": "" if m.revoked_at else m.body,
            "revoked": bool(m.revoked_at),
            "media": None
            if m.revoked_at
            else _media(child, "out", m.id, m.media_file, m.media_name, m.media_type),
        }
        for m in outbound.order_by("-created_at")[:THREAD_LIMIT]
    ]
    items.sort(key=lambda item: item["at"])
    return {"center": child.organization.name, "results": items[-THREAD_LIMIT:]}


def send(phone, child, text, file=None):
    """Сообщение из кабинета — в CRM как входящее WhatsApp-сообщение родителя.
    file — фото, голосовое, видео или документ (text — подпись к нему)."""
    from domains.platform.core.attachments import NOTE_EXTENSIONS, VIDEO_EXTENSIONS, files_error
    from domains.platform.notifications.messaging.whatsapp import route_inbound_message
    from domains.platform.notifications.models import InboundWhatsAppMessage

    text = (text or "").strip()
    if not text and file is None:
        raise ChatError("Напишите сообщение или прикрепите файл.")
    if file is not None:
        error = files_error(
            [file],
            allowed=NOTE_EXTENSIONS | VIDEO_EXTENSIONS,
            max_files=1,
            max_bytes=16 * 1024 * 1024,
        )
        if error:
            raise ChatError(error)
    if len(text) > 4096:
        raise ChatError("Сообщение не должно быть длиннее 4096 символов.")
    contacts, inbound, _outbound = _queries(phone, child)
    if not contacts:
        raise ChatError("Не нашли вашу карточку в центре.")
    recent = inbound.filter(
        message_type=PORTAL_MESSAGE_TYPE, created_at__gte=timezone.now() - RATE_WINDOW
    ).count()
    if recent >= RATE_LIMIT:
        raise ChatError("Слишком много сообщений подряд — подождите минуту.")
    parent = contacts[0]
    message = InboundWhatsAppMessage.objects.create(
        organization=child.organization,
        provider_message_id=f"portal:{uuid.uuid4()}",
        sender_phone=_phone(phone),
        sender_name=parent.full_name,
        message_type=PORTAL_MESSAGE_TYPE,
        text=text,
        # Как у вложений из WhatsApp: подпись — caption, имя и тип файла.
        media={
            key: value
            for key, value in {
                "caption": text,
                "filename": file.name[:255],
                "mime_type": (file.content_type or "")[:100],
            }.items()
            if value
        }
        if file is not None
        else {},
        media_file=file,
        provider_sent_at=timezone.now(),
    )
    # Та же маршрутизация, что у WhatsApp: в историю родителя и ребёнка.
    route_inbound_message(message.id)
    return message


def delete(phone, child, direction, message_id, *, for_everyone=False):
    """Родитель удаляет сообщение: у себя (только в кабинете) или у всех —
    своё из кабинета, тогда и в CRM будет «Сообщение удалено»."""
    _contacts_, inbound, outbound = _queries(phone, child)
    rows = inbound if direction == "in" else outbound
    message = rows.filter(pk=message_id).first() if direction in ("in", "out") else None
    if message is None:
        return None
    now = timezone.now()
    if for_everyone:
        if direction != "in" or not _can_revoke(message):
            raise ChatError(
                "У всех можно удалить только своё сообщение из кабинета за последние 48 часов."
            )
        message.revoked_at = now
        message.save(update_fields=["revoked_at", "updated_at"])
    else:
        message.parent_hidden_at = now
        message.save(update_fields=["parent_hidden_at", "updated_at"])
    return message


def media_message(phone, child, direction, message_id):
    _contacts_, inbound, outbound = _queries(phone, child)
    rows = inbound if direction == "in" else outbound
    return rows.filter(pk=message_id, revoked_at__isnull=True).first()
