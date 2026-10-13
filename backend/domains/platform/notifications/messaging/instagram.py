"""Instagram Graph API transport, inbound routing and safe replies (TRU-173)."""

import hashlib
import hmac
import json
import re
import secrets
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from domains.people.clients.models import ChildContact, CommunicationLog
from domains.platform.leads.models import LeadCampaign, LeadComment, LeadSource
from domains.platform.leads.services import create_lead
from domains.platform.users.models import User

from ..models import (
    InboundInstagramMessage,
    InstagramConnection,
    InstagramIdentity,
)

QUESTION_WORDS = re.compile(
    r"(?:\?|сколько|цена|стоим|расписан|когда|возраст|лет|группа|мест|"
    r"запис|адрес|где|пробн|абонем|бағасы|қанша|кесте|жас|топ|орын|мекен)",
    re.IGNORECASE,
)
MENTION_ONLY = re.compile(r"^(?:\s*@[-\w.]+\s*)+$")
PUBLIC_PRIVATE_DATA = re.compile(
    r"(?:\+?\d[\d\s()\-]{8,}|\b(?:долг|задолж|оплат|телефон|номер|" r"қарыз|төлем)\w*\b|₸|тенге)",
    re.IGNORECASE,
)


class InstagramError(Exception):
    pass


def new_verify_token():
    return secrets.token_urlsafe(32)


def connection_for(organization):
    return InstagramConnection.objects.for_tenant(organization).first()


def _request(connection, method, path, payload=None):
    url = f"https://graph.facebook.com/{settings.INSTAGRAM_GRAPH_API_VERSION}/{path}"
    if method == "GET":
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}access_token={connection.access_token}"
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
        with urllib.request.urlopen(request, timeout=settings.INSTAGRAM_HTTP_TIMEOUT) as response:
            return json.loads(response.read() or b"{}")
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        detail = getattr(exc, "read", lambda: b"")().decode(errors="replace")
        raise InstagramError((detail or str(exc))[:500]) from exc


def verify_connection(connection):
    if connection.mode == InstagramConnection.Mode.CONSOLE:
        return {"id": connection.instagram_account_id or "console-instagram", "username": "demo"}
    if not settings.INSTAGRAM_APP_SECRET:
        raise InstagramError("Добавьте INSTAGRAM_APP_SECRET в настройки сервера.")
    if not (connection.instagram_account_id and connection.facebook_page_id):
        raise InstagramError("Укажите Instagram Business Account ID и Facebook Page ID.")
    if not connection.access_token:
        raise InstagramError("Укажите токен доступа Meta.")
    return _request(
        connection,
        "GET",
        f"{connection.instagram_account_id}?fields=id,username,profile_picture_url",
    )


def valid_webhook_signature(raw_body, signature):
    secret = settings.INSTAGRAM_APP_SECRET
    if not secret:
        return True
    if not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature.removeprefix("sha256="), expected)


def looks_like_lead(text):
    """Conservative comment filter: reactions and friend tags never enter the funnel."""
    value = (text or "").strip()
    if len(value) < 3 or MENTION_ONLY.fullmatch(value):
        return False
    if not re.search(r"[A-Za-zА-Яа-яӘәҒғҚқҢңӨөҰұҮүҺһІі]", value):
        return False
    return bool(QUESTION_WORDS.search(value))


def _system_author(organization):
    return (
        User.objects.filter(organization=organization, is_active=True, role=User.Role.OWNER)
        .order_by("created_at")
        .first()
        or User.objects.filter(organization=organization, is_active=True)
        .order_by("created_at")
        .first()
    )


def _source(organization, kind):
    name = (
        "Instagram Direct"
        if kind == InboundInstagramMessage.Kind.DIRECT
        else "Instagram комментарий"
    )
    return LeadSource.objects.get_or_create(
        organization=organization, name=name, defaults={"is_active": True}
    )[0]


def _campaign(message, source):
    if not message.ad_id:
        return None
    code = "IG" + hashlib.sha1(message.ad_id.encode()).hexdigest()[:8].upper()  # noqa: S324
    return LeadCampaign.objects.get_or_create(
        organization=message.organization,
        code=code,
        defaults={
            "source": source,
            "name": (message.ad_name or f"Instagram {message.ad_id}")[:100],
            "is_active": True,
        },
    )[0]


def _link_to_child(message, child, parent, user=None):
    author = user or _system_author(message.organization)
    if not author:
        message.status = InboundInstagramMessage.Status.UNRESOLVED
        message.resolution_note = "Нет активного сотрудника для истории коммуникаций"
        message.save(update_fields=["status", "resolution_note", "updated_at"])
        return message
    log = CommunicationLog.objects.create(
        organization=message.organization,
        child=child,
        parent_contact=parent,
        channel=CommunicationLog.Channel.COMMENT,
        note=f"Instagram {message.get_kind_display()}: {message.text}",
        author=author,
    )
    message.parent = parent
    message.child = child
    message.communication_log = log
    message.status = InboundInstagramMessage.Status.LINKED
    message.resolution_note = "Добавлено в историю коммуникаций ребёнка"
    message.resolved_by = user
    message.resolved_at = timezone.now()
    message.save()
    if parent and message.sender_id:
        InstagramIdentity.objects.update_or_create(
            organization=message.organization,
            scoped_user_id=message.sender_id,
            defaults={"parent": parent, "username": message.sender_name},
        )
    return message


def _link_to_lead(message, lead, user=None):
    details = [f"Instagram {message.get_kind_display()}: {message.text}"]
    if message.post_url:
        details.append(message.post_url)
    LeadComment.objects.create(
        organization=message.organization,
        lead=lead,
        author=user,
        text="\n".join(details),
    )
    message.lead = lead
    message.status = InboundInstagramMessage.Status.LINKED
    message.resolution_note = "Добавлено в историю заявки"
    message.resolved_by = user
    message.resolved_at = timezone.now()
    message.save()
    return message


@transaction.atomic
def route_inbound_message(message_id, *, user=None, force_lead=False):
    message = InboundInstagramMessage.objects.select_for_update().get(pk=message_id)
    if message.status == InboundInstagramMessage.Status.LINKED:
        return message
    if message.kind == InboundInstagramMessage.Kind.COMMENT and not (
        message.lead_candidate or force_lead
    ):
        message.status = InboundInstagramMessage.Status.IGNORED
        message.resolution_note = "Комментарий не похож на вопрос о занятиях"
        message.save(update_fields=["status", "resolution_note", "updated_at"])
        return message
    if force_lead:
        message.manually_promoted = True
        message.lead_candidate = True
    identity = (
        InstagramIdentity.objects.for_tenant(message.organization)
        .filter(scoped_user_id=message.sender_id)
        .select_related("parent")
        .first()
    )
    if identity:
        children = {
            link.child_id: link.child
            for link in ChildContact.objects.for_tenant(message.organization)
            .filter(parent_contact=identity.parent)
            .select_related("child")
        }
        if len(children) == 1:
            return _link_to_child(message, next(iter(children.values())), identity.parent, user)
        message.parent = identity.parent
        message.status = InboundInstagramMessage.Status.UNRESOLVED
        message.resolution_note = "У контакта несколько детей — выберите карточку вручную"
        message.save()
        return message
    source = _source(message.organization, message.kind)
    campaign = _campaign(message, source)
    lead = create_lead(
        organization=message.organization,
        actor=user,
        parent_name=message.sender_name or f"Instagram {message.sender_id}",
        phone="",
        source=source,
        campaign=campaign,
    )
    return _link_to_lead(message, lead, user)


@transaction.atomic
def resolve_inbound_message(message, *, child=None, lead=None, user=None):
    message = InboundInstagramMessage.objects.select_for_update().get(pk=message.pk)
    if message.status == InboundInstagramMessage.Status.LINKED:
        raise ValueError("Сообщение уже привязано")
    if bool(child) == bool(lead):
        raise ValueError("Выберите ребёнка или заявку")
    target = child or lead
    if target.organization_id != message.organization_id:
        raise ValueError("Карточка из другой организации")
    if child:
        link = (
            ChildContact.objects.for_tenant(message.organization)
            .filter(child=child)
            .select_related("parent_contact")
            .order_by("-is_primary_contact")
            .first()
        )
        return _link_to_child(message, child, link.parent_contact if link else None, user)
    return _link_to_lead(message, lead, user)


def _event_rows(payload):
    for entry in payload.get("entry", []):
        for item in entry.get("messaging", []):
            incoming = item.get("message") or {}
            if not incoming or incoming.get("is_echo"):
                continue
            yield {
                "id": incoming.get("mid"),
                "kind": "direct",
                "sender_id": (item.get("sender") or {}).get("id", ""),
                "sender_name": (item.get("sender") or {}).get("username", ""),
                "text": incoming.get("text", ""),
                "timestamp": item.get("timestamp"),
                "raw": item,
            }
        for change in entry.get("changes", []):
            if change.get("field") not in {"comments", "live_comments"}:
                continue
            value = change.get("value") or {}
            sender = value.get("from") or {}
            media = value.get("media") or {}
            yield {
                "id": value.get("id"),
                "kind": "comment",
                "sender_id": sender.get("id", ""),
                "sender_name": sender.get("username", ""),
                "text": value.get("text", ""),
                "post_id": media.get("id", ""),
                "post_url": media.get("permalink", ""),
                "ad_id": value.get("ad_id", ""),
                "ad_name": value.get("ad_name", ""),
                "timestamp": value.get("created_time"),
                "raw": value,
            }


def handle_webhook(payload):
    changed = 0
    for entry in payload.get("entry", []):
        account_id = str(entry.get("id", ""))
        connection = InstagramConnection.objects.filter(instagram_account_id=account_id).first()
        if not connection:
            continue
        scoped = {"entry": [entry]}
        for row in _event_rows(scoped):
            event_id = (
                row["id"]
                or hashlib.sha256(json.dumps(row["raw"], sort_keys=True).encode()).hexdigest()
            )
            timestamp = row.get("timestamp")
            if isinstance(timestamp, int | float):
                sent_at = datetime.fromtimestamp(timestamp / 1000, tz=UTC)
            else:
                sent_at = timezone.now()
            text = (row.get("text") or "").strip()
            kind = row["kind"]
            message, created = InboundInstagramMessage.objects.get_or_create(
                organization=connection.organization,
                provider_event_id=event_id,
                defaults={
                    "kind": kind,
                    "sender_id": row.get("sender_id", ""),
                    "sender_name": row.get("sender_name", ""),
                    "text": text,
                    "post_id": row.get("post_id", ""),
                    "post_url": row.get("post_url", ""),
                    "ad_id": row.get("ad_id", ""),
                    "ad_name": row.get("ad_name", ""),
                    "raw_payload": row["raw"],
                    "provider_sent_at": sent_at,
                    "lead_candidate": kind == "direct" or looks_like_lead(text),
                },
            )
            if created:
                route_inbound_message(message.id)
                changed += 1
    return changed


def send_reply(message, text):
    body = (text or "").strip()
    if not body:
        raise InstagramError("Введите текст ответа.")
    if message.kind == InboundInstagramMessage.Kind.COMMENT:
        private_values = [message.parent.full_name if message.parent_id else ""]
        if message.child_id:
            private_values.append(message.child.full_name)
        if PUBLIC_PRIVATE_DATA.search(body) or any(
            value and value.lower() in body.lower() for value in private_values
        ):
            raise InstagramError("В публичном комментарии нельзя отправлять личные данные.")
    connection = connection_for(message.organization)
    if not connection or connection.status != InstagramConnection.Status.CONNECTED:
        raise InstagramError("Instagram центра не подключён.")
    if connection.token_expires_at and connection.token_expires_at <= timezone.now():
        raise InstagramError("Токен Instagram истёк. Обновите подключение.")
    if connection.mode == InstagramConnection.Mode.CONSOLE:
        return f"console-instagram-{message.id}"
    if message.kind == InboundInstagramMessage.Kind.COMMENT:
        response = _request(
            connection, "POST", f"{message.provider_event_id}/replies", {"message": body}
        )
    else:
        if message.provider_sent_at and message.provider_sent_at < timezone.now() - timedelta(
            hours=24
        ):
            raise InstagramError("Окно свободного ответа Direct (24 часа) закрыто.")
        response = _request(
            connection,
            "POST",
            f"{connection.instagram_account_id}/messages",
            {"recipient": {"id": message.sender_id}, "message": {"text": body}},
        )
    return str(response.get("id") or response.get("message_id") or "")
