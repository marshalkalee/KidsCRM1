"""API центра рассылок (TRU-168): настройки, тексты, журнал, согласие,
публичная страница отписки."""

from html import escape

from django.core import signing
from django.http import HttpResponse
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from domains.people.clients.models import ParentContact
from domains.platform.core.permissions import IsOwner, IsOwnerOrManagerOrAdmin
from domains.platform.tenants.org_settings import (
    MESSAGING_CHANNELS,
    MESSAGING_QUIET_FROM,
    MESSAGING_QUIET_TO,
    MESSAGING_REPLY_TO,
    get_org_setting,
)

from ..models import MessageCategory, MessageTemplate, MessagingConsent, OutboundMessage
from . import service
from .channels import CHANNELS
from .events import EVENTS, LANGUAGES

JOURNAL_LIMIT = 200


# --- Настройки -------------------------------------------------------------


@api_view(["GET", "PUT"])
@permission_classes([IsOwner])
def messaging_settings(request, version=None):
    organization = request.user.organization
    if request.method == "PUT":
        data = request.data
        errors = {}
        try:
            quiet_from = int(data.get("quiet_from"))
            quiet_to = int(data.get("quiet_to"))
            if not (0 <= quiet_from <= 23 and 0 <= quiet_to <= 23):
                raise ValueError
        except (TypeError, ValueError):
            errors["quiet_from"] = ["Часы — от 0 до 23."]
        channels = data.get("channels")
        if (
            not isinstance(channels, list)
            or not channels
            or any(c not in CHANNELS for c in channels)
        ):
            errors["channels"] = ["Выберите хотя бы один канал."]
        reply_to = (data.get("reply_to") or "").strip()
        if reply_to and "@" not in reply_to:
            errors["reply_to"] = ["Это не похоже на email."]
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)
        organization.settings = {
            **organization.settings,
            MESSAGING_QUIET_FROM: quiet_from,
            MESSAGING_QUIET_TO: quiet_to,
            MESSAGING_CHANNELS: list(dict.fromkeys(channels)),
            MESSAGING_REPLY_TO: reply_to,
        }
        organization.save(update_fields=["settings", "updated_at"])
    return Response(
        {
            "quiet_from": get_org_setting(organization, MESSAGING_QUIET_FROM),
            "quiet_to": get_org_setting(organization, MESSAGING_QUIET_TO),
            "channels": get_org_setting(organization, MESSAGING_CHANNELS),
            "reply_to": get_org_setting(organization, MESSAGING_REPLY_TO),
            "available_channels": [
                {
                    "key": key,
                    "label": channel.label,
                    "connected": not getattr(channel, "reason", ""),
                    "reason": getattr(channel, "reason", ""),
                }
                for key, channel in CHANNELS.items()
            ],
        }
    )


# --- Тексты ----------------------------------------------------------------


@api_view(["GET"])
@permission_classes([IsOwner])
def templates(request, version=None):
    organization = request.user.organization
    own = {
        (t.event, t.language): t
        for t in MessageTemplate.objects.for_tenant(organization).filter(channel="email")
    }
    rows = []
    for event in EVENTS.values():
        languages = {}
        for language in LANGUAGES:
            default_subject, default_body = service.default_template(event.key, "email", language)
            mine = own.get((event.key, language))
            languages[language] = {
                "subject": mine.subject if mine else default_subject,
                "body": mine.body if mine else default_body,
                "customized": mine is not None,
            }
        rows.append(
            {
                "event": event.key,
                "label": event.label,
                "category": event.category,
                "variables": event.all_variables,
                "email": languages,
            }
        )
    return Response(rows)


@api_view(["PUT", "DELETE"])
@permission_classes([IsOwner])
def template_detail(request, event, language, version=None):
    organization = request.user.organization
    if event not in EVENTS or language not in LANGUAGES:
        return Response({"detail": "Нет такого шаблона."}, status=status.HTTP_404_NOT_FOUND)
    rows = MessageTemplate.objects.for_tenant(organization).filter(
        event=event, channel="email", language=language
    )
    if request.method == "DELETE":
        rows.delete()  # вернуть текст по умолчанию
        return Response(status=status.HTTP_204_NO_CONTENT)
    subject = (request.data.get("subject") or "").strip()
    body = (request.data.get("body") or "").strip()
    if not subject or not body:
        return Response({"detail": "Нужны тема и текст."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        service.validate_template(event, subject, body)
    except service.MessagingError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    MessageTemplate.objects.update_or_create(
        organization=organization,
        event=event,
        channel="email",
        language=language,
        defaults={"subject": subject[:200], "body": body},
    )
    return Response({"subject": subject, "body": body, "customized": True})


# --- Журнал ----------------------------------------------------------------


def _message_row(m):
    return {
        "id": str(m.id),
        "created_at": m.created_at,
        "sent_at": m.sent_at,
        "scheduled_for": m.scheduled_for,
        "parent": {"id": str(m.parent_id), "name": m.parent.full_name},
        "event": m.event,
        "event_label": EVENTS[m.event].label if m.event in EVENTS else m.event,
        "status": m.status,
        "status_label": m.get_status_display(),
        "channel": m.channel,
        "recipient": m.recipient,
        "subject": m.subject,
        "body": m.body,
        "error": m.error,
        "attempts": m.attempts,
    }


@api_view(["GET"])
@permission_classes([IsOwnerOrManagerOrAdmin])
def journal(request, version=None):
    """Что и кому отправили: фильтры — родитель, статус, событие, период."""
    rows = OutboundMessage.objects.for_tenant(request.user.organization).select_related("parent")
    params = request.query_params
    if params.get("parent"):
        rows = rows.filter(parent_id=params["parent"])
    if params.get("status"):
        rows = rows.filter(status__in=params["status"].split(","))
    if params.get("event"):
        rows = rows.filter(event=params["event"])
    if day := parse_date(params.get("date_from") or ""):
        rows = rows.filter(created_at__date__gte=day)
    if day := parse_date(params.get("date_to") or ""):
        rows = rows.filter(created_at__date__lte=day)
    return Response(
        {
            "results": [_message_row(m) for m in rows[:JOURNAL_LIMIT]],
            "total": rows.count(),
            "limit": JOURNAL_LIMIT,
            "events": [{"key": e.key, "label": e.label} for e in EVENTS.values()],
            "statuses": [{"key": k, "label": v} for k, v in OutboundMessage.Status.choices],
        }
    )


# --- Согласие родителя --------------------------------------------------------


def _consent_payload(parent):
    rows = {
        c.category: c
        for c in MessagingConsent.objects.for_tenant(parent.organization).filter(parent=parent)
    }
    return {
        category: (
            {
                "status": rows[category].status,
                "source": rows[category].source,
                "source_label": rows[category].get_source_display(),
                "changed_at": rows[category].changed_at,
            }
            if category in rows
            else None
        )
        for category in MessageCategory.values
    }


@api_view(["GET", "PUT"])
@permission_classes([IsOwnerOrManagerOrAdmin])
def parent_consent(request, parent_id, version=None):
    """Согласие на сообщения в карточке родителя. Сотрудник включает только
    служебные (по анкете или договору центра); если родитель отписался сам —
    включить может только он. Рекламные сотрудник может только выключить."""
    parent = (
        ParentContact.objects.for_tenant(request.user.organization).filter(pk=parent_id).first()
    )
    if parent is None:
        return Response({"detail": "Родитель не найден."}, status=status.HTTP_404_NOT_FOUND)
    if request.method == "PUT":
        for category in MessageCategory.values:
            if category not in request.data:
                continue
            enable = bool(request.data[category])
            current = (
                MessagingConsent.objects.for_tenant(parent.organization)
                .filter(parent=parent, category=category)
                .first()
            )
            if enable and category == MessageCategory.MARKETING:
                return Response(
                    {"detail": "Согласие на рекламные сообщения даёт только сам родитель."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if (
                enable
                and current
                and current.status == MessagingConsent.Status.OPTED_OUT
                and current.source != MessagingConsent.Source.ADMIN_FORM
            ):
                return Response(
                    {"detail": "Родитель отписался сам — снова включить может только он."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            new_status = (
                MessagingConsent.Status.OPTED_IN if enable else MessagingConsent.Status.OPTED_OUT
            )
            if current is None or current.status != new_status:
                service.set_consent(
                    parent,
                    category,
                    new_status,
                    MessagingConsent.Source.ADMIN_FORM,
                    user=request.user,
                )
    return Response(_consent_payload(parent))


# --- Отписка по ссылке из письма (публичная) ------------------------------------

_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:32rem;margin:15vh auto;
padding:0 1rem;color:#1f2937}}
button{{font:inherit;padding:.6rem 1.2rem;border-radius:.5rem;border:0;
background:#ef4444;color:#fff;cursor:pointer}}
</style>
</head><body><h1 style="font-size:1.4rem">{title}</h1><p>{text}</p>{form}</body></html>"""


@api_view(["GET", "POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def unsubscribe(request, token, version=None):
    """GET — страница с кнопкой (почтовые сканеры открывают ссылки сами,
    поэтому сама ссылка ничего не меняет). POST — отписка, в том числе
    «в один клик» из почтового клиента (RFC 8058)."""
    try:
        data = signing.loads(token, salt=service.UNSUBSCRIBE_SALT)
    except signing.BadSignature:
        return HttpResponse(
            _PAGE.format(title="Ссылка устарела", text="Напишите центру напрямую.", form=""),
            status=400,
        )
    kind = "рекламных" if data.get("c") == MessageCategory.MARKETING else "служебных"
    if request.method == "GET":
        return HttpResponse(
            _PAGE.format(
                title="Отписаться от писем",
                text=f"Вы больше не будете получать {kind} писем от центра.",
                form='<form method="post"><button type="submit">Отписаться</button></form>',
            )
        )
    try:
        parent, _ = service.unsubscribe(token)
    except signing.BadSignature:
        return HttpResponse(
            _PAGE.format(title="Ссылка устарела", text="Напишите центру напрямую.", form=""),
            status=400,
        )
    return HttpResponse(
        _PAGE.format(
            title="Вы отписались",
            text=escape(
                f"Писем от «{parent.organization.name}» больше не будет. "
                "Передумаете — скажите администратору или включите в кабинете родителя."
            ),
            form="",
        )
    )
