"""
Центр рассылок родителям (TRU-168, ADR-0010) — единственная точка, через
которую система пишет родителю.

    notify(parent, "payment_due", {"child": "Алия", "amount": "25 000 ₸"},
           dedup_key=f"payment_due:{subscription.id}:{month}")

- Веб-запрос не ждёт: строка журнала и задача в очереди (ТЗ п. 10.1).
- Одно событие — одно сообщение: dedup_key уникален в центре, повторный
  вызов возвращает ту же строку.
- Без согласия не отправляем, отписка сильнее всего (ТЗ п. 10.3, Meta).
- Тихие часы по времени центра: ночью — откладываем до утра.
- Каналы по порядку из настроек центра, первый отправивший — последний.
"""

import datetime
import logging
import string
import uuid
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core import signing
from django.db import IntegrityError, transaction
from django.utils import timezone

from domains.platform.core.audit import AuditLog
from domains.platform.tenants.org_settings import (
    MESSAGING_CHANNELS,
    MESSAGING_QUIET_FROM,
    MESSAGING_QUIET_TO,
    get_org_setting,
)

from ..models import MessageCategory, MessageTemplate, MessagingConsent, OutboundMessage
from .channels import CHANNELS, ChannelError, ChannelLater
from .events import EVENTS, LANGUAGES, UNSUBSCRIBE_FOOTER
from .recipients import accounts_for_parent

logger = logging.getLogger(__name__)
Status = OutboundMessage.Status
UNSUBSCRIBE_SALT = "messaging-unsubscribe"


class MessagingError(Exception):
    """Ошибка вызывающего кода (неизвестное событие, нет подстановки)."""


# --- Согласие --------------------------------------------------------------


def consent_status(parent, category) -> str | None:
    row = (
        MessagingConsent.objects.for_tenant(parent.organization)
        .filter(parent=parent, category=category)
        .values_list("status", flat=True)
        .first()
    )
    return row


def set_consent(parent, category, status, source, user=None) -> MessagingConsent:
    """Изменить согласие и записать в журнал действий: кто, когда, откуда."""
    consent = (
        MessagingConsent.objects.for_tenant(parent.organization)
        .filter(parent=parent, category=category)
        .first()
    )
    before = {"status": consent.status, "source": consent.source} if consent else None
    if consent is None:
        consent = MessagingConsent(
            organization=parent.organization, parent=parent, category=category
        )
    consent.status = status
    consent.source = source
    consent.changed_by = user
    consent.changed_at = timezone.now()
    consent.save()
    AuditLog.record(
        actor=user,
        action=AuditLog.Action.UPDATE,
        entity=consent,
        before=before,
        after={"status": status, "source": source, "category": category},
    )
    return consent


def unsubscribe_token(message) -> str:
    return signing.dumps(
        {"o": str(message.organization_id), "p": str(message.parent_id), "c": message.category},
        salt=UNSUBSCRIBE_SALT,
    )


def unsubscribe_url(message) -> str:
    return f"{settings.PUBLIC_BASE_URL}/api/v1/messaging/unsubscribe/{unsubscribe_token(message)}/"


def unsubscribe(token: str):
    """Ссылка из письма: отписать родителя от категории этого письма.
    Возвращает (родитель, категория) или бросает signing.BadSignature."""
    from domains.people.clients.models import ParentContact

    data = signing.loads(token, salt=UNSUBSCRIBE_SALT)
    parent = ParentContact.objects.filter(pk=data["p"], organization_id=data["o"]).first()
    if parent is None:
        raise signing.BadSignature("parent not found")
    if consent_status(parent, data["c"]) != MessagingConsent.Status.OPTED_OUT:
        set_consent(
            parent,
            data["c"],
            MessagingConsent.Status.OPTED_OUT,
            MessagingConsent.Source.UNSUBSCRIBE_LINK,
        )
    return parent, data["c"]


# --- Тексты ----------------------------------------------------------------


def template_vars(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def default_template(event_key, channel, language) -> tuple[str, str]:
    event = EVENTS[event_key]
    if channel == "push" and event.push:
        return event.push.get(language) or event.push["ru"]
    # Тексты WhatsApp утверждает Meta — TRU-169; до него — текст письма.
    return event.email.get(language) or event.email["ru"]


def template_for(organization, event_key, channel, language) -> tuple[str, str]:
    own = (
        MessageTemplate.objects.for_tenant(organization)
        .filter(event=event_key, channel=channel, language=language)
        .first()
    )
    if own:
        return own.subject, own.body
    return default_template(event_key, channel, language)


def validate_template(event_key, subject, body):
    """Только подстановки этого события — иначе шаблон упадёт на отправке."""
    allowed = set(EVENTS[event_key].all_variables)
    unknown = (template_vars(subject) | template_vars(body)) - allowed
    if unknown:
        raise MessagingError(
            "Неизвестные подстановки: "
            + ", ".join("{" + v + "}" for v in sorted(unknown))
            + ". Можно: "
            + ", ".join("{" + v + "}" for v in sorted(allowed))
        )


def render(text: str, values: dict) -> str:
    class Missing(dict):
        def __missing__(self, key):
            return ""

    return text.format_map(Missing(values)).strip()


def portal_text(message, language: str) -> tuple[str, str]:
    """Текст для колокольчика кабинета — короткий, как push: без
    приветствия и без подвала письма со ссылкой отписки."""
    values = {
        "parent": parent_name(message.parent),
        "center": message.organization.name,
        **{key: value for key, value in message.context.items() if not key.startswith("_")},
    }
    title, body = template_for(message.organization, message.event, "push", language)
    return render(title, values), render(body, values)


def parent_language(parent) -> str:
    """Язык кабинета родителя (по любому его номеру), иначе русский."""
    language = accounts_for_parent(parent).values_list("language", flat=True).first()
    return language if language in LANGUAGES else "ru"


def parent_name(parent) -> str:
    """Как обращаемся к родителю: ФИО полностью, как записано в карточке.
    Из ФИО имя не угадываем — его пишут и «Фамилия Имя», и «Имя Фамилия»."""
    return " ".join((parent.full_name or "").split())


# --- Тихие часы --------------------------------------------------------------


def quiet_until(organization, now=None) -> datetime.datetime | None:
    """Если сейчас тихие часы центра — когда они кончатся, иначе None."""
    tz = ZoneInfo(organization.timezone or "Asia/Almaty")
    local = timezone.localtime(now or timezone.now(), tz)
    start = get_org_setting(organization, MESSAGING_QUIET_FROM)
    end = get_org_setting(organization, MESSAGING_QUIET_TO)
    if start == end:
        return None
    hour = local.hour
    quiet = (start <= hour or hour < end) if start > end else (start <= hour < end)
    if not quiet:
        return None
    day = local.date() if hour < end else local.date() + datetime.timedelta(days=1)
    return datetime.datetime.combine(day, datetime.time(end), tzinfo=tz)


# --- Отправка ----------------------------------------------------------------


def notify(
    parent, event_key, context=None, *, dedup_key, user=None, countdown=None
) -> OutboundMessage:
    """Поставить сообщение родителю в очередь. Повтор с тем же dedup_key —
    та же строка журнала, второго сообщения не будет. countdown — через
    сколько секунд отправить (массовая отправка идёт не одним залпом)."""
    event = EVENTS.get(event_key)
    if event is None:
        raise MessagingError(f"Неизвестное событие: {event_key}")
    organization = parent.organization
    existing = OutboundMessage.objects.for_tenant(organization).filter(dedup_key=dedup_key).first()
    if existing:
        return existing
    try:
        with transaction.atomic():
            message = OutboundMessage.objects.create(
                organization=organization,
                parent=parent,
                event=event_key,
                category=event.category,
                dedup_key=dedup_key,
                context={k: str(v) for k, v in (context or {}).items()},
                created_by=user,
            )
    except IntegrityError:
        # Параллельный вызов успел первым — его строка и есть наше сообщение.
        return OutboundMessage.objects.for_tenant(organization).get(dedup_key=dedup_key)
    _enqueue(
        message, eta=timezone.now() + datetime.timedelta(seconds=countdown) if countdown else None
    )
    return message


def notify_whatsapp_reply(parent, body, *, user=None) -> OutboundMessage:
    """Ответ сотрудника обычным текстом. Канал перепроверяет, можно ли (окно
    Meta), и отправляет с номера, на который родитель писал последним."""
    from .whatsapp import last_inbound_connection_id

    text = (body or "").strip()
    if not text:
        raise MessagingError("Введите текст ответа.")
    if len(text) > 4096:
        raise MessagingError("Ответ не должен быть длиннее 4096 символов.")
    context = {"_channel": "whatsapp", "_free_text": text}
    connection_id = last_inbound_connection_id(parent)
    if connection_id:
        context["_connection"] = str(connection_id)
    message = OutboundMessage.objects.create(
        organization=parent.organization,
        parent=parent,
        event="whatsapp_reply",
        category=MessageCategory.UTILITY,
        dedup_key=f"whatsapp-reply:{uuid.uuid4()}",
        context=context,
        created_by=user,
    )
    if user is not None:
        from domains.people.clients.models import CommunicationLog

        CommunicationLog.objects.create(
            organization=parent.organization,
            parent_contact=parent,
            channel=CommunicationLog.Channel.WHATSAPP,
            note=text,
            author=user,
        )
    _enqueue(message)
    return message


def _enqueue(message, eta=None):
    from .tasks import deliver_message

    transaction.on_commit(
        lambda: deliver_message.apply_async(args=[str(message.id)], eta=eta)
        if eta
        else deliver_message.delay(str(message.id))
    )


def _finish(message, status, **fields):
    message.status = status
    for name, value in fields.items():
        setattr(message, name, value)
    message.save()
    return message


def deliver(message_id, now=None) -> OutboundMessage:
    """Задача очереди: проверить согласие и тихие часы, перебрать каналы."""
    with transaction.atomic():
        message = (
            OutboundMessage.objects.select_for_update(of=("self",))
            .select_related("organization", "parent")
            .get(pk=message_id)
        )
        # Задача выполнилась второй раз — сообщение уже в работе или ушло.
        if message.status not in (Status.QUEUED, Status.DEFERRED):
            return message
        _finish(message, Status.SENDING)

    parent, organization = message.parent, message.organization
    consent = consent_status(parent, message.category)
    if consent == MessagingConsent.Status.OPTED_OUT:
        return _finish(message, Status.OPTED_OUT)
    if consent != MessagingConsent.Status.OPTED_IN:
        return _finish(message, Status.NO_CONSENT)
    # Родитель сам отключил этот тип в профиле кабинета — по всем каналам.
    if any(
        prefs.get(message.event) is False
        for prefs in accounts_for_parent(parent).values_list("notification_prefs", flat=True)
    ):
        return _finish(message, Status.OPTED_OUT, error="Родитель отключил этот тип в кабинете")

    wait_until = quiet_until(organization, now)
    if wait_until:
        _finish(message, Status.DEFERRED, scheduled_for=wait_until)
        _enqueue(message, eta=wait_until)
        return message

    language = parent_language(parent)
    values = {
        "parent": parent_name(parent),
        "center": organization.name,
        **message.context,
    }
    attempts = []
    forced_channel = message.context.get("_channel")
    channel_keys = (
        [forced_channel] if forced_channel else get_org_setting(organization, MESSAGING_CHANNELS)
    )
    for key in channel_keys:
        channel = CHANNELS.get(key)
        if channel is None:
            continue
        recipient, reason = channel.recipient(parent)
        if recipient is None:
            attempts.append({"channel": key, "result": "skipped", "reason": reason})
            continue
        message.channel, message.recipient, message.language = key, recipient, language
        link = unsubscribe_url(message)
        if key == "whatsapp" and message.event == "whatsapp_reply":
            message.subject = ""
            message.body = message.context.get("_free_text", "")
        else:
            subject, body = template_for(organization, message.event, key, language)
            message.subject = render(subject, values)[:200]
            message.body = render(body, values)
        if key == "email":
            message.body += UNSUBSCRIBE_FOOTER[language].format(
                center=organization.name, unsubscribe_url=link
            )
        try:
            provider_id = channel.send(message, unsubscribe_url=link)
        except ChannelLater as exc:
            # Номер WhatsApp занят очередью: ждём своей очереди, а не уходим в email.
            _finish(message, Status.QUEUED, scheduled_for=exc.retry_at, attempts=attempts)
            _enqueue(message, eta=exc.retry_at)
            return message
        except ChannelError as exc:
            attempts.append({"channel": key, "result": "failed", "error": str(exc)})
            continue
        attempts.append({"channel": key, "result": "sent"})
        return _finish(
            message, Status.SENT, provider_id=provider_id, attempts=attempts, sent_at=timezone.now()
        )

    failed = [a for a in attempts if a["result"] == "failed"]
    if failed:
        return _finish(message, Status.FAILED, attempts=attempts, error=failed[-1]["error"][:500])
    return _finish(
        message,
        Status.NO_CHANNEL,
        attempts=attempts,
        error="; ".join(a["reason"] for a in attempts)[:500],
    )


def on_email_event(provider_id, event_type, description="") -> OutboundMessage | None:
    """Вебхук почтового провайдера (через anymail): недоставка и жалоба.
    Жалоба на письмо = отписка от этой категории."""
    message = (
        OutboundMessage.objects.filter(provider_id=provider_id).first() if provider_id else None
    )
    if message is None:
        return None
    if event_type == "delivered" and message.status == Status.SENT:
        return _finish(message, Status.DELIVERED)
    if event_type in ("bounced", "rejected", "failed"):
        return _finish(message, Status.FAILED, error=f"Не доставлено: {description}"[:500])
    if event_type in ("complained", "unsubscribed"):
        set_consent(
            message.parent,
            message.category,
            MessagingConsent.Status.OPTED_OUT,
            MessagingConsent.Source.EMAIL_COMPLAINT,
        )
    return message


# --- Сообщение сотрудника с номера центра --------------------------------------
#
# Кнопка «WhatsApp» в карточках, задачах и списках: сотрудник правит готовый
# текст и отправляет его с номера центра (по QR-коду), а не со своего
# телефона. Получатель — родитель, заявка или ребёнок по номеру из CRM.
# Это обычная переписка, не рассылка: тихие часы и согласие на рассылки не
# проверяются.

MANUAL_EVENT = "whatsapp_manual"


def send_manual_whatsapp(user, text, *, phone="", parent=None, lead=None, child=None, file=None):
    from domains.people.clients.models import CommunicationLog
    from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number

    from .whatsapp import connection_for, find_contact, last_inbound_connection_id

    organization = user.organization
    text = (text or "").strip()
    if not text and file is None:
        raise MessagingError("Введите текст сообщения или прикрепите файл.")
    if len(text) > 4096:
        raise MessagingError("Сообщение не должно быть длиннее 4096 символов.")
    raw = phone or (
        (parent.whatsapp or parent.phones.values_list("number", flat=True).first())
        if parent
        else lead.phone
        if lead
        else ""
    )
    try:
        recipient = normalize_phone_number(raw)
    except InvalidPhoneNumberError as exc:
        raise MessagingError("У получателя нет корректного номера WhatsApp.") from exc
    if parent is None and lead is None:
        parent, lead = find_contact(organization, recipient)
    if parent is None and lead is None:
        # Номер центра — не шлюз для любых номеров: только свои родители и заявки.
        raise MessagingError("Номер не найден среди родителей и заявок центра.")
    previous = last_inbound_connection_id(organization=organization, phone=recipient)
    connection = connection_for(organization, parent, previous, qr_only=True)
    if connection is None or connection.status != connection.Status.CONNECTED:
        raise MessagingError("WhatsApp центра не подключён.")
    message = OutboundMessage.objects.create(
        organization=organization,
        parent=parent,
        lead=lead,
        event=MANUAL_EVENT,
        category=MessageCategory.UTILITY,
        dedup_key=f"{MANUAL_EVENT}:{uuid.uuid4()}",
        context={"_channel": "whatsapp", "_connection": str(connection.pk)},
        channel="whatsapp",
        recipient=recipient,
        language=parent_language(parent) if parent else "ru",
        body=text,
        created_by=user,
    )
    if file is not None:
        # Файл — подпись в body; уходит как фото, видео, документ или голосовое.
        message.media_name = file.name[:255]
        message.media_type = (file.content_type or "")[:100]
        message.media_file = file
        message.save(update_fields=["media_name", "media_type", "media_file", "updated_at"])
    # Заявке — только в чат заявки; родителю — ещё и в историю карточки.
    if parent:
        # Ребёнок — если писали из его карточки, иначе запись о родителе.
        CommunicationLog.objects.create(
            organization=organization,
            child=child,
            parent_contact=parent,
            channel=CommunicationLog.Channel.WHATSAPP,
            note=f"{text}\nФайл: {file.name}".strip() if file else text,
            author=user,
        )
    from .tasks import send_manual_whatsapp_task

    transaction.on_commit(lambda: send_manual_whatsapp_task.delay(str(message.id)))
    return message


def deliver_manual(message_id) -> OutboundMessage:
    """Задача очереди: отправить сообщение сотрудника с выбранного номера."""
    from .whatsapp import WhatsAppError, WhatsAppLater, _send_evolution, connection_for

    with transaction.atomic():
        message = (
            OutboundMessage.objects.select_for_update(of=("self",))
            .select_related("organization", "parent")
            .get(pk=message_id)
        )
        if message.status != Status.QUEUED:
            return message
        _finish(message, Status.SENDING)
    connection = connection_for(
        message.organization, message.parent, message.context.get("_connection"), qr_only=True
    )
    if connection is None or connection.status != connection.Status.CONNECTED:
        return _finish(message, Status.FAILED, error="WhatsApp центра не подключён")
    try:
        provider_id = _send_evolution(connection, message)
    except WhatsAppLater as exc:
        from .tasks import send_manual_whatsapp_task

        retry_at = exc.retry_at
        _finish(message, Status.QUEUED, scheduled_for=retry_at)
        transaction.on_commit(
            lambda: send_manual_whatsapp_task.apply_async(args=[str(message.id)], eta=retry_at)
        )
        return message
    except WhatsAppError as exc:
        return _finish(
            message,
            Status.FAILED,
            error=str(exc)[:500],
            attempts=[{"channel": "whatsapp", "result": "failed", "error": str(exc)}],
        )
    return _finish(
        message,
        Status.SENT,
        provider_id=provider_id,
        sent_at=timezone.now(),
        attempts=[{"channel": "whatsapp", "result": "sent"}],
    )


__all__ = [
    "MANUAL_EVENT",
    "MessageCategory",
    "MessagingError",
    "consent_status",
    "deliver",
    "deliver_manual",
    "notify",
    "notify_whatsapp_reply",
    "send_manual_whatsapp",
    "set_consent",
    "unsubscribe",
]
