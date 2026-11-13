"""WhatsApp: Meta Cloud API (TRU-169) и номера по QR-коду через Evolution API.

Транспорт выбирается по режиму подключения (WhatsAppConnection.mode); всё
остальное — маршрутизация входящих и привязка к карточкам — общее."""

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
from domains.platform.leads.models import Lead, LeadSource
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


class WhatsAppLater(WhatsAppError):
    """Номер занят очередью — сообщение отправится в retry_at, не другим каналом."""

    def __init__(self, retry_at):
        super().__init__("Очередь отправки номера занята")
        self.retry_at = retry_at


STOP_WORDS = {"stop", "стоп", "тоқта", "токта"}


def parent_branch_ids(parent) -> set:
    """Филиалы, где сейчас занимаются дети родителя."""
    from domains.scheduling.groups.models import GroupMembership

    return set(
        GroupMembership.objects.filter(
            child__in=ChildContact.objects.filter(parent_contact=parent).values("child_id"),
            left_at__isnull=True,
            deleted_at__isnull=True,
            group__branch__isnull=False,
        ).values_list("group__branch_id", flat=True)
    )


def connection_for(organization, parent=None, connection_id=None, *, qr_only=False):
    """Номер, с которого писать: тот, на который родитель писал (connection_id),
    номер филиала ребёнка, номер всего центра, любой подключённый. Нет
    подключённых — первая строка (чтобы показать её статус) или None.
    qr_only — только номера по QR-коду: первым писать незнакомому можно лишь с них."""
    rows = WhatsAppConnection.objects.for_tenant(organization).select_related("branch")
    if qr_only:
        rows = rows.filter(mode=WhatsAppConnection.Mode.EVOLUTION)
    rows = list(rows)
    connected = [row for row in rows if row.status == WhatsAppConnection.Status.CONNECTED]
    if not connected:
        return rows[0] if rows else None
    if connection_id:
        chosen = next((row for row in connected if str(row.pk) == str(connection_id)), None)
        if chosen:
            return chosen
    if parent is not None and any(row.branch_id for row in connected):
        branches = parent_branch_ids(parent)
        chosen = next((row for row in connected if row.branch_id in branches), None)
        if chosen:
            return chosen
    return next((row for row in connected if not row.branch_id), connected[0])


def is_evolution(connection) -> bool:
    return bool(connection and connection.mode == WhatsAppConnection.Mode.EVOLUTION)


def free_text_allowed(parent, connection=None) -> bool:
    """Обычный текст можно всегда с номера по QR-коду; в Meta — только в
    24-часовом окне после сообщения родителя."""
    connection = connection or connection_for(parent.organization, parent)
    return is_evolution(connection) or within_service_window(parent)


def last_inbound_connection_id(parent=None, *, organization=None, phone=""):
    """Номер центра, на который родитель (или человек с этим телефоном) писал
    последним, — ответ уйдёт с него."""
    rows = InboundWhatsAppMessage.objects.for_tenant(organization or parent.organization).filter(
        connection__isnull=False
    )
    rows = rows.filter(parent=parent) if parent is not None else rows.filter(sender_phone=phone)
    return rows.order_by("-created_at").values_list("connection_id", flat=True).first()


def find_contact(organization, phone):
    """Кто в CRM с этим номером: (родитель, заявка). Родитель важнее заявки."""
    parent = _parent_by_phone(organization, phone)
    if parent:
        return parent, None
    leads = Lead.objects.for_tenant(organization).filter(phone=phone)
    lead = (
        leads.exclude(status__in=[Lead.Status.PURCHASED, Lead.Status.REJECTED])
        .order_by("-created_at")
        .first()
        or leads.order_by("-created_at").first()
    )
    return None, lead


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


def _send_evolution(connection, message):
    from .evolution import EvolutionError, SendLater, send_media, send_text

    try:
        if message.media_file:
            return send_media(connection, message.recipient, message)
        return send_text(connection, message.recipient, message.body)
    except SendLater as exc:
        raise WhatsAppLater(exc.retry_at) from exc
    except EvolutionError as exc:
        raise WhatsAppError(str(exc)) from exc


def send_template(message):
    connection = connection_for(message.organization, message.parent)
    if not connection or connection.status != WhatsAppConnection.Status.CONNECTED:
        raise WhatsAppError("WhatsApp центра не подключён")
    if is_evolution(connection):
        # Без шаблонов Meta: уходит обычный текст события.
        return _send_evolution(connection, message)
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
    """Ответ сотрудника. Meta — только в 24-часовом окне; номер по QR — всегда."""
    connection = connection_for(
        message.organization, message.parent, message.context.get("_connection")
    )
    if not connection or connection.status != WhatsAppConnection.Status.CONNECTED:
        raise WhatsAppError("WhatsApp центра не подключён")
    if is_evolution(connection):
        return _send_evolution(connection, message)
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
    parent = (
        ParentContact.objects.for_tenant(organization)
        .filter(whatsapp=phone, deleted_at__isnull=True)
        .first()
    )
    if parent:
        return parent
    # Телефоны удалённого родителя остаются в базе — такого родителя не ищем:
    # его номер снова «незнакомый», сообщение пойдёт в заявку.
    contact = (
        ContactPhone.objects.for_tenant(organization)
        .filter(number=phone, parent_contact__deleted_at__isnull=True)
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


def _inbound_log(message, parent, child=None):
    """Входящее в ленте «Коммуникации»: автора-сотрудника нет — написал
    родитель. Уже есть запись (о родителе) — уточняем ребёнка, без дубля."""
    log = message.communication_log
    if log is not None:
        if child is not None and log.child_id is None:
            log.child = child
            log.save(update_fields=["child", "updated_at"])
        return log
    return CommunicationLog.objects.create(
        organization=message.organization,
        child=child,
        parent_contact=parent,
        channel=CommunicationLog.Channel.WHATSAPP,
        note=message.text
        or (
            f"Файл: {message.media.get('filename')}"
            if message.media.get("filename")
            else f"Входящий файл WhatsApp: {message.message_type}"
        ),
        author=None,
    )


def _link_to_child(message, child, parent, *, resolved_by=None):
    log = _inbound_log(message, parent, child)
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
    # Само сообщение — в чате заявки; в заметки не копируем, чтобы не дублировать.
    message.lead = lead
    message.status = InboundWhatsAppMessage.Status.LINKED
    message.resolution_note = "Добавлено в чат заявки"
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
    if not message.sender_phone:
        # WhatsApp скрыл номер (аккаунт с @lid): заявка по имени из WhatsApp,
        # следующие сообщения того же человека — в ту же заявку.
        jid = (message.raw_payload.get("key") or {}).get("remoteJid") or ""
        earlier = (
            InboundWhatsAppMessage.objects.for_tenant(message.organization)
            .filter(raw_payload__key__remoteJid=jid, lead__isnull=False)
            .exclude(pk=message.pk)
            .order_by("-created_at")
            .first()
            if jid
            else None
        )
        if earlier:
            return _link_to_lead(message, earlier.lead, resolved_by=resolved_by)
        return _link_to_lead(message, _new_lead(message), resolved_by=resolved_by)
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
        # Детей нет или несколько — сообщение в истории и чате родителя.
        message.parent = parent
        message.communication_log = _inbound_log(message, parent)
        message.status = InboundWhatsAppMessage.Status.LINKED
        message.resolution_note = "Добавлено в историю родителя"
        message.resolved_at = timezone.now()
        message.save()
        return message
    # Открытых заявок с этим номером несколько — в самую свежую.
    lead = (
        Lead.objects.for_tenant(message.organization)
        .filter(phone=message.sender_phone)
        .exclude(status__in=[Lead.Status.PURCHASED, Lead.Status.REJECTED])
        .order_by("-created_at")
        .first()
    )
    return _link_to_lead(message, lead or _new_lead(message), resolved_by=resolved_by)


def _new_lead(message):
    """Новая заявка из WhatsApp — в филиале номера, на который написали.
    Как ручная: статус «Новая», время статуса и первая строка истории."""
    from domains.platform.leads.services import create_lead

    source, _ = LeadSource.objects.get_or_create(
        organization=message.organization, name="WhatsApp", defaults={"is_active": True}
    )
    return create_lead(
        organization=message.organization,
        actor=None,
        branch=message.connection.branch if message.connection_id else None,
        parent_name=message.sender_name
        or (f"WhatsApp {message.sender_phone}" if message.sender_phone else "WhatsApp"),
        phone=message.sender_phone,
        source=source,
    )


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
                provider_message_id = incoming.get("id") or (
                    "missing-"
                    + hashlib.sha256(json.dumps(incoming, sort_keys=True).encode()).hexdigest()
                )
                stored = store_inbound(
                    connection,
                    {
                        "provider_message_id": provider_message_id,
                        "sender_phone": sender_phone,
                        "message_type": incoming.get("type", "text"),
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
                changed += int(stored is not None)
    return changed


def store_inbound(connection, fields):
    """Сохранить входящее один раз и разложить по карточкам.
    None — дубль (провайдер прислал повторно)."""
    sender_phone = fields.get("sender_phone") or ""
    recent_count = (
        InboundWhatsAppMessage.objects.for_tenant(connection.organization)
        .filter(
            sender_phone=sender_phone,
            created_at__gte=timezone.now() - timedelta(minutes=1),
        )
        .count()
        if sender_phone
        else 0
    )
    message, created = InboundWhatsAppMessage.objects.get_or_create(
        organization=connection.organization,
        provider_message_id=fields["provider_message_id"],
        defaults={
            **{key: value for key, value in fields.items() if key != "provider_message_id"},
            "connection": connection,
        },
    )
    if not created:
        # Evolution прислал событие повторно — второй копии файла не нужно.
        if fields.get("media_file"):
            from django.core.files.storage import default_storage

            default_storage.delete(fields["media_file"])
        return None
    if recent_count >= 30:
        message.status = InboundWhatsAppMessage.Status.IGNORED
        message.resolution_note = "Лимит входящих сообщений с одного номера"
        message.save(update_fields=["status", "resolution_note", "updated_at"])
        return message
    try:
        route_inbound_message(message.id)
    except Exception:
        logger.exception("Failed to route WhatsApp message %s", message.id)
        message.status = InboundWhatsAppMessage.Status.FAILED
        message.resolution_note = "Ошибка обработки — повторите или привяжите вручную"
        message.save(update_fields=["status", "resolution_note", "updated_at"])
        return message
    message.refresh_from_db()
    parent = message.parent
    # «Стоп» как отписка — правило Meta для официального API. На номере по
    # QR-коду это обычная переписка: слово «стоп» в чате ничего не отключает.
    if (
        parent
        and not is_evolution(connection)
        and message.text.strip().strip('.!»«"').casefold() in STOP_WORDS
    ):
        from .service import set_consent

        for category in ("utility", "marketing"):
            set_consent(
                parent,
                category,
                MessagingConsent.Status.OPTED_OUT,
                MessagingConsent.Source.WHATSAPP_REPLY,
            )
    return message


def handle_evolution_webhook(connection_id, payload):
    """Событие Evolution API для одного номера (вебхук → очередь → сюда)."""
    from domains.platform.tasks.models import Task

    from .evolution import apply_delivery, apply_state, parse_incoming

    connection = (
        WhatsAppConnection.objects.filter(
            pk=connection_id, mode=WhatsAppConnection.Mode.EVOLUTION, deleted_at__isnull=True
        )
        .select_related("organization", "branch")
        .first()
    )
    if connection is None:
        return 0
    event = str(payload.get("event") or "").lower().replace("_", ".")
    data = payload.get("data")
    if event == "connection.update" and isinstance(data, dict):
        dropped = apply_state(connection, data.get("state"), wuid=data.get("wuid") or "")
        if dropped:
            owner = (
                connection.organization.users.filter(is_active=True, role=User.Role.OWNER)
                .order_by("created_at")
                .first()
            )
            Task.objects.get_or_create(
                organization=connection.organization,
                source_key=f"whatsapp-disconnected:{connection.pk}:{timezone.localdate()}",
                defaults={
                    "type": Task.Type.OTHER,
                    "source": Task.Source.AUTO,
                    "status": Task.Status.OPEN,
                    "title": f"WhatsApp отключился: {connection.label}",
                    "description": (
                        "Сообщения родителям с этого номера не уходят — пока номер не "
                        "подключён, они идут другими каналами. Рассылки → Настройки → "
                        "WhatsApp → «Подключить»."
                    ),
                    "assigned_to": owner,
                    "branch": connection.branch,
                    "due_at": timezone.now(),
                },
            )
        return 1
    if event == "messages.delete":
        # Удалено у всех в WhatsApp — родителем или с телефона центра.
        rows = data if isinstance(data, list) else [data]
        changed = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = row.get("key") if isinstance(row.get("key"), dict) else row
            provider_id = key.get("id") or ""
            if not provider_id:
                continue
            model = OutboundMessage if key.get("fromMe") else InboundWhatsAppMessage
            field = "provider_id" if key.get("fromMe") else "provider_message_id"
            changed += (
                model.objects.for_tenant(connection.organization)
                .filter(**{field: provider_id}, revoked_at__isnull=True)
                .update(revoked_at=timezone.now())
            )
        return changed
    if event == "messages.update":
        rows = data if isinstance(data, list) else [data]
        return sum(apply_delivery(connection, row) for row in rows if isinstance(row, dict))
    if event == "messages.upsert":
        rows = data if isinstance(data, list) else [data]
        changed = 0
        for row in rows:
            fields = parse_incoming(row) if isinstance(row, dict) else None
            # История чатов, подтянутая при подключении, — не новые сообщения.
            if fields is None or (
                connection.connected_at
                and fields["provider_sent_at"] < connection.connected_at - timedelta(minutes=5)
            ):
                # Файл сохранили в вебхуке заранее — сообщение не наше, файл не нужен.
                if isinstance(row, dict) and row.get("_media_path"):
                    from django.core.files.storage import default_storage

                    default_storage.delete(row["_media_path"])
                continue
            changed += int(store_inbound(connection, fields) is not None)
        return changed
    return 0


def new_verify_token():
    return secrets.token_urlsafe(32)
