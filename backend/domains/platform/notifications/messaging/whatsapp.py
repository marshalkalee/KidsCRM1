"""Meta WhatsApp Cloud API transport and webhook contract (TRU-169)."""

import hashlib
import hmac
import json
import logging
import secrets
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from domains.people.clients.models import (
    ChildContact,
    CommunicationLog,
    ContactPhone,
    ParentContact,
)
from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number
from domains.platform.leads.models import Lead, LeadComment, LeadSource
from domains.platform.users.models import User

from ..models import (
    InboundWhatsAppMessage,
    MessageTemplate,
    MessagingConsent,
    OutboundMessage,
    WhatsAppConnection,
    WhatsAppContactWindow,
)
from .events import EVENTS, LANGUAGES

logger = logging.getLogger(__name__)
WINDOW = timedelta(hours=24)
META_STATUS = {
    "PENDING": MessageTemplate.ProviderStatus.PENDING,
    "APPROVED": MessageTemplate.ProviderStatus.APPROVED,
    "REJECTED": MessageTemplate.ProviderStatus.REJECTED,
    "PAUSED": MessageTemplate.ProviderStatus.REJECTED,
    "DISABLED": MessageTemplate.ProviderStatus.REJECTED,
}


class WhatsAppError(Exception):
    pass


def connection_for(organization):
    return WhatsAppConnection.objects.for_tenant(organization).filter().first()


def template_name(event, language):
    return f"kidscrm_{event}_{language}"


def within_service_window(parent, now=None):
    last = (
        WhatsAppContactWindow.objects.for_tenant(parent.organization)
        .filter(parent=parent)
        .values_list("last_inbound_at", flat=True)
        .first()
    )
    return bool(last and last >= (now or timezone.now()) - WINDOW)


def _request(connection, method, path, payload=None):
    url = f"https://graph.facebook.com/{settings.WHATSAPP_GRAPH_API_VERSION}/{path}"
    request = urllib.request.Request(
        url,
        method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={
            "Authorization": f"Bearer {connection.access_token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.WHATSAPP_HTTP_TIMEOUT) as response:
            return json.loads(response.read() or b"{}")
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        detail = getattr(exc, "read", lambda: b"")().decode(errors="replace")
        raise WhatsAppError((detail or str(exc))[:500]) from exc


def verify_connection(connection):
    if connection.mode == WhatsAppConnection.Mode.CONSOLE:
        return {"display_phone_number": connection.business_phone or "+77000000000"}
    if not settings.WHATSAPP_APP_SECRET:
        raise WhatsAppError("Добавьте WHATSAPP_APP_SECRET в настройки сервера.")
    if not (connection.phone_number_id and connection.waba_id and connection.access_token):
        raise WhatsAppError("Укажите WABA ID, Phone number ID и токен доступа.")
    return _request(connection, "GET", connection.phone_number_id)


def ensure_default_templates(connection):
    """Create local rows and synchronize their review statuses with Meta."""
    organization = connection.organization
    rows = []
    remote = {}
    if connection.mode == WhatsAppConnection.Mode.META:
        response = _request(connection, "GET", f"{connection.waba_id}/message_templates?limit=100")
        remote = {item.get("name"): item for item in response.get("data", [])}
    for event in EVENTS.values():
        for language in LANGUAGES:
            _subject, body = event.email.get(language) or event.email["ru"]
            row, _ = MessageTemplate.objects.update_or_create(
                organization=organization,
                event=event.key,
                channel="whatsapp",
                language=language,
                defaults={"body": body, "subject": ""},
            )
            name = template_name(event.key, language)
            item = remote.get(name)
            if connection.mode == WhatsAppConnection.Mode.CONSOLE:
                row.provider_status = MessageTemplate.ProviderStatus.APPROVED
                row.provider_template_id = name
                row.rejection_reason = ""
            elif item:
                row.provider_status = META_STATUS.get(
                    item.get("status"), MessageTemplate.ProviderStatus.PENDING
                )
                row.provider_template_id = str(item.get("id", ""))
                row.rejection_reason = item.get("rejected_reason") or ""
            elif row.provider_status != MessageTemplate.ProviderStatus.APPROVED:
                # Meta-шаблоны создаются и проходят проверку в Business Manager.
                # Здесь только синхронизируем их состояние, чтобы CRM никогда не
                # отправила локальный черновик как будто он уже одобрен Meta.
                row.provider_status = MessageTemplate.ProviderStatus.DRAFT
                row.provider_template_id = ""
            row.synced_at = timezone.now()
            row.save(
                update_fields=[
                    "provider_status",
                    "provider_template_id",
                    "rejection_reason",
                    "synced_at",
                    "updated_at",
                ]
            )
            rows.append(row)
    return rows


def send_template(message):
    connection = connection_for(message.organization)
    if not connection or connection.status != WhatsAppConnection.Status.CONNECTED:
        raise WhatsAppError("WhatsApp центра не подключён")
    template = (
        MessageTemplate.objects.for_tenant(message.organization)
        .filter(event=message.event, channel="whatsapp", language=message.language)
        .first()
    )
    if not template or template.provider_status != MessageTemplate.ProviderStatus.APPROVED:
        reason = template.rejection_reason if template else "шаблон ещё не синхронизирован"
        raise WhatsAppError(f"Шаблон Meta не одобрен: {reason}")
    if connection.mode == WhatsAppConnection.Mode.CONSOLE:
        provider_id = f"console-wa-{message.id}"
        logger.info(
            "WhatsApp console to=%s body=%s id=%s",
            message.recipient,
            message.body,
            provider_id,
        )
        return provider_id
    values = {
        "parent": message.parent.full_name,
        "center": message.organization.name,
        **message.context,
    }
    parameters = [
        {"type": "text", "parameter_name": name, "text": str(values.get(name, ""))}
        for name in EVENTS[message.event].all_variables
    ]
    response = _request(
        connection,
        "POST",
        f"{connection.phone_number_id}/messages",
        {
            "messaging_product": "whatsapp",
            "to": message.recipient.lstrip("+"),
            "type": "template",
            "template": {
                "name": template_name(message.event, message.language),
                "language": {"code": message.language},
                "components": [{"type": "body", "parameters": parameters}],
            },
        },
    )
    try:
        return response["messages"][0]["id"]
    except (KeyError, IndexError) as exc:
        raise WhatsAppError("Meta не вернула ID сообщения") from exc


def send_free_text(message):
    """Send a human reply only while Meta's 24-hour service window is open."""
    connection = connection_for(message.organization)
    if not connection or connection.status != WhatsAppConnection.Status.CONNECTED:
        raise WhatsAppError("WhatsApp центра не подключён")
    if not within_service_window(message.parent):
        raise WhatsAppError("24-часовое окно ответа закрылось. Используйте одобренный шаблон Meta.")
    if connection.mode == WhatsAppConnection.Mode.CONSOLE:
        provider_id = f"console-wa-reply-{message.id}"
        logger.info(
            "WhatsApp console reply to=%s body=%s id=%s",
            message.recipient,
            message.body,
            provider_id,
        )
        return provider_id
    response = _request(
        connection,
        "POST",
        f"{connection.phone_number_id}/messages",
        {
            "messaging_product": "whatsapp",
            "to": message.recipient.lstrip("+"),
            "type": "text",
            "text": {"preview_url": False, "body": message.body},
        },
    )
    try:
        return response["messages"][0]["id"]
    except (KeyError, IndexError) as exc:
        raise WhatsAppError("Meta не вернула ID сообщения") from exc


def valid_webhook_signature(raw_body, signature):
    """Validate Meta's X-Hub-Signature-256 when an app secret is configured."""
    secret = settings.WHATSAPP_APP_SECRET
    if not secret:
        return True
    if not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature.removeprefix("sha256="), expected)


def _parent_by_phone(organization, raw_phone):
    try:
        phone = normalize_phone_number(raw_phone)
    except InvalidPhoneNumberError:
        return None
    parent = ParentContact.objects.for_tenant(organization).filter(whatsapp=phone).first()
    if parent:
        return parent
    contact = (
        ContactPhone.objects.for_tenant(organization)
        .filter(number=phone)
        .select_related("parent_contact")
        .first()
    )
    return contact.parent_contact if contact else None


def _message_text(incoming):
    kind = incoming.get("type", "text")
    if kind == "text":
        return (incoming.get("text") or {}).get("body", "").strip()
    media = incoming.get(kind) or {}
    return (media.get("caption") or media.get("filename") or f"[{kind}]").strip()


def _message_media(incoming):
    kind = incoming.get("type", "text")
    if kind not in {"image", "document", "audio", "video", "sticker"}:
        return {}
    value = incoming.get(kind) or {}
    return {
        key: value[key]
        for key in ("id", "mime_type", "sha256", "filename", "caption")
        if value.get(key)
    }


def _system_author(organization):
    return (
        User.objects.filter(organization=organization, is_active=True, role=User.Role.OWNER)
        .order_by("created_at")
        .first()
        or User.objects.filter(organization=organization, is_active=True)
        .order_by("created_at")
        .first()
    )


def _link_to_child(message, child, parent, *, resolved_by=None):
    author = resolved_by or _system_author(message.organization)
    if author is None:
        message.status = InboundWhatsAppMessage.Status.UNRESOLVED
        message.resolution_note = "Нет активного сотрудника для журнала коммуникаций"
        message.save(update_fields=["status", "resolution_note", "updated_at"])
        return message
    log = CommunicationLog.objects.create(
        organization=message.organization,
        child=child,
        parent_contact=parent,
        channel=CommunicationLog.Channel.WHATSAPP,
        note=message.text or f"Входящий файл WhatsApp: {message.message_type}",
        author=author,
    )
    message.parent = parent
    message.child = child
    message.communication_log = log
    message.status = InboundWhatsAppMessage.Status.LINKED
    message.resolution_note = "Добавлено в историю коммуникаций ребёнка"
    message.resolved_by = resolved_by
    message.resolved_at = timezone.now()
    message.save()
    if parent:
        WhatsAppContactWindow.objects.update_or_create(
            organization=message.organization,
            parent=parent,
            defaults={"last_inbound_at": message.provider_sent_at or timezone.now()},
        )
    return message


def _open_service_window(message, parent):
    if parent:
        WhatsAppContactWindow.objects.update_or_create(
            organization=message.organization,
            parent=parent,
            defaults={"last_inbound_at": message.provider_sent_at or timezone.now()},
        )


def _link_to_lead(message, lead, *, resolved_by=None):
    LeadComment.objects.create(
        organization=message.organization,
        lead=lead,
        author=resolved_by,
        text=f"WhatsApp: {message.text or f'[{message.message_type}]'}",
    )
    message.lead = lead
    message.status = InboundWhatsAppMessage.Status.LINKED
    message.resolution_note = "Добавлено в историю заявки"
    message.resolved_by = resolved_by
    message.resolved_at = timezone.now()
    message.save()
    return message


@transaction.atomic
def route_inbound_message(message_id, *, resolved_by=None):
    """Route exactly once; ambiguous matches remain in the manual inbox."""
    message = InboundWhatsAppMessage.objects.select_for_update().get(pk=message_id)
    if message.status == InboundWhatsAppMessage.Status.LINKED:
        return message
    message.status = InboundWhatsAppMessage.Status.PROCESSING
    message.save(update_fields=["status", "updated_at"])
    parent = _parent_by_phone(message.organization, message.sender_phone)
    if parent:
        _open_service_window(message, parent)
        links = list(
            ChildContact.objects.for_tenant(message.organization)
            .filter(parent_contact=parent)
            .select_related("child")
        )
        children = {link.child_id: link.child for link in links}
        if len(children) == 1:
            return _link_to_child(
                message, next(iter(children.values())), parent, resolved_by=resolved_by
            )
        message.parent = parent
        message.status = InboundWhatsAppMessage.Status.UNRESOLVED
        message.resolution_note = (
            "У контакта несколько детей — выберите карточку вручную"
            if children
            else "Контакт найден, но ребёнок не привязан"
        )
        message.save()
        return message
    leads = list(
        Lead.objects.for_tenant(message.organization)
        .filter(phone=message.sender_phone)
        .exclude(status__in=[Lead.Status.PURCHASED, Lead.Status.REJECTED])[:2]
    )
    if len(leads) == 1:
        return _link_to_lead(message, leads[0], resolved_by=resolved_by)
    if len(leads) > 1:
        message.status = InboundWhatsAppMessage.Status.UNRESOLVED
        message.resolution_note = "Найдено несколько открытых заявок — выберите вручную"
        message.save()
        return message
    source, _ = LeadSource.objects.get_or_create(
        organization=message.organization, name="WhatsApp", defaults={"is_active": True}
    )
    lead = Lead.objects.create(
        organization=message.organization,
        parent_name=f"WhatsApp {message.sender_phone}",
        phone=message.sender_phone,
        source=source,
        status=Lead.Status.NEW,
    )
    return _link_to_lead(message, lead, resolved_by=resolved_by)


@transaction.atomic
def resolve_inbound_message(message, *, child=None, lead=None, user=None):
    message = InboundWhatsAppMessage.objects.select_for_update().get(pk=message.pk)
    if message.status == InboundWhatsAppMessage.Status.LINKED:
        raise ValueError("Сообщение уже привязано")
    if bool(child) == bool(lead):
        raise ValueError("Выберите ребёнка или заявку")
    target = child or lead
    if target.organization_id != message.organization_id:
        raise ValueError("Карточка из другой организации")
    if child:
        parent = message.parent or _parent_by_phone(message.organization, message.sender_phone)
        return _link_to_child(message, child, parent, resolved_by=user)
    return _link_to_lead(message, lead, resolved_by=user)


def handle_webhook(payload):
    """Apply delivery receipts and update the 24-hour service window."""
    changed = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            phone_number_id = value.get("metadata", {}).get("phone_number_id")
            connection = WhatsAppConnection.objects.filter(phone_number_id=phone_number_id).first()
            if not connection:
                continue
            for status_row in value.get("statuses", []):
                message = OutboundMessage.objects.filter(
                    organization=connection.organization, provider_id=status_row.get("id", "")
                ).first()
                if not message:
                    continue
                state = status_row.get("status")
                if state in ("sent", "delivered", "read"):
                    message.status = state
                    message.error = ""
                elif state == "failed":
                    message.status = OutboundMessage.Status.FAILED
                    errors = status_row.get("errors") or []
                    message.error = str(errors[0].get("title", "Не доставлено"))[:500]
                message.save(update_fields=["status", "error", "updated_at"])
                changed += 1
            for incoming in value.get("messages", []):
                try:
                    sender_phone = normalize_phone_number(incoming.get("from", ""))
                except InvalidPhoneNumberError:
                    continue
                recent_count = (
                    InboundWhatsAppMessage.objects.for_tenant(connection.organization)
                    .filter(
                        sender_phone=sender_phone,
                        created_at__gte=timezone.now() - timedelta(minutes=1),
                    )
                    .count()
                )
                kind = incoming.get("type", "text")
                provider_message_id = incoming.get("id") or (
                    "missing-"
                    + hashlib.sha256(json.dumps(incoming, sort_keys=True).encode()).hexdigest()
                )
                message, created = InboundWhatsAppMessage.objects.get_or_create(
                    organization=connection.organization,
                    provider_message_id=provider_message_id,
                    defaults={
                        "sender_phone": sender_phone,
                        "message_type": kind,
                        "text": _message_text(incoming),
                        "media": _message_media(incoming),
                        "raw_payload": incoming,
                        "provider_sent_at": datetime.fromtimestamp(
                            int(incoming["timestamp"]), tz=UTC
                        )
                        if incoming.get("timestamp")
                        else timezone.now(),
                    },
                )
                if not created:
                    continue
                if recent_count >= 30:
                    message.status = InboundWhatsAppMessage.Status.IGNORED
                    message.resolution_note = "Лимит входящих сообщений с одного номера"
                    message.save(update_fields=["status", "resolution_note", "updated_at"])
                    continue
                try:
                    route_inbound_message(message.id)
                except Exception:
                    logger.exception("Failed to route WhatsApp message %s", message.id)
                    message.status = InboundWhatsAppMessage.Status.FAILED
                    message.resolution_note = "Ошибка обработки — повторите или привяжите вручную"
                    message.save(update_fields=["status", "resolution_note", "updated_at"])
                    continue
                message.refresh_from_db()
                parent = message.parent
                text = message.text.casefold()
                if text in {"stop", "стоп", "тоқта"}:
                    from .service import set_consent

                    for category in ("utility", "marketing") if parent else ():
                        set_consent(
                            parent,
                            category,
                            MessagingConsent.Status.OPTED_OUT,
                            MessagingConsent.Source.WHATSAPP_REPLY,
                        )
                changed += 1
    return changed


def new_verify_token():
    return secrets.token_urlsafe(32)
