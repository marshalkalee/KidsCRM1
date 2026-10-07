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
from .channels import CHANNELS, ChannelError
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


def parent_language(parent) -> str:
    """Язык кабинета родителя (по любому его номеру), иначе русский."""
    language = accounts_for_parent(parent).values_list("language", flat=True).first()
    return language if language in LANGUAGES else "ru"


def _first_name(full_name: str) -> str:
    parts = (full_name or "").split()
    return parts[1] if len(parts) > 1 else (parts[0] if parts else "")


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


def notify(parent, event_key, context=None, *, dedup_key, user=None) -> OutboundMessage:
    """Поставить сообщение родителю в очередь. Повтор с тем же dedup_key —
    та же строка журнала, второго сообщения не будет."""
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
            OutboundMessage.objects.select_for_update()
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
        "parent": _first_name(parent.full_name),
        "center": organization.name,
        **message.context,
    }
    attempts = []
    for key in get_org_setting(organization, MESSAGING_CHANNELS):
        channel = CHANNELS.get(key)
        if channel is None:
            continue
        recipient, reason = channel.recipient(parent)
        if recipient is None:
            attempts.append({"channel": key, "result": "skipped", "reason": reason})
            continue
        subject, body = template_for(organization, message.event, key, language)
        message.channel, message.recipient, message.language = key, recipient, language
        message.subject = render(subject, values)[:200]
        link = unsubscribe_url(message)
        message.body = render(body, values)
        if key == "email":
            message.body += UNSUBSCRIBE_FOOTER[language].format(
                center=organization.name, unsubscribe_url=link
            )
        try:
            provider_id = channel.send(message, unsubscribe_url=link)
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


__all__ = [
    "MessageCategory",
    "MessagingError",
    "consent_status",
    "deliver",
    "notify",
    "set_consent",
    "unsubscribe",
]
