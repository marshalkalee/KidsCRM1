"""Meta WhatsApp Cloud API transport and webhook contract (TRU-169)."""

import hashlib
import hmac
import json
import logging
import secrets
import urllib.error
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from domains.people.clients.models import ContactPhone, ParentContact
from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number

from ..models import (
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
                parent = _parent_by_phone(connection.organization, incoming.get("from", ""))
                if not parent:
                    continue
                WhatsAppContactWindow.objects.update_or_create(
                    organization=connection.organization,
                    parent=parent,
                    defaults={"last_inbound_at": timezone.now()},
                )
                text = (incoming.get("text") or {}).get("body", "").strip().casefold()
                if text in {"stop", "стоп", "тоқта"}:
                    from .service import set_consent

                    for category in ("utility", "marketing"):
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
