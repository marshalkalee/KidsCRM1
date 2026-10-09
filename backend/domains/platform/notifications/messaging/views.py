"""API центра рассылок (TRU-168): настройки, тексты, журнал, согласие,
публичная страница отписки."""

from html import escape

from django.core import signing
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from domains.people.clients.models import ChildContact, ParentContact
from domains.platform.core.permissions import IsOwner, IsOwnerOrManagerOrAdmin
from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number
from domains.platform.tenants.org_settings import (
    MESSAGING_CHANNELS,
    MESSAGING_QUIET_FROM,
    MESSAGING_QUIET_TO,
    MESSAGING_REPLY_TO,
    get_org_setting,
)

from ..models import (
    MessageCategory,
    MessageTemplate,
    MessagingConsent,
    OutboundMessage,
    WhatsAppConnection,
)
from . import service
from .channels import CHANNELS
from .events import EVENTS, LANGUAGES
from .whatsapp import (
    WhatsAppError,
    ensure_default_templates,
    handle_webhook,
    new_verify_token,
    template_name,
    valid_webhook_signature,
    verify_connection,
    within_service_window,
)

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
                    "connected": (
                        WhatsAppConnection.objects.for_tenant(organization)
                        .filter(status=WhatsAppConnection.Status.CONNECTED)
                        .exists()
                        if key == "whatsapp"
                        else not getattr(channel, "reason", "")
                    ),
                    "reason": (
                        "WhatsApp центра не подключён"
                        if key == "whatsapp"
                        and not WhatsAppConnection.objects.for_tenant(organization)
                        .filter(status=WhatsAppConnection.Status.CONNECTED)
                        .exists()
                        else getattr(channel, "reason", "")
                    ),
                }
                for key, channel in CHANNELS.items()
            ],
        }
    )


def _connection_payload(connection):
    if not connection:
        return {
            "mode": "console",
            "status": "disconnected",
            "waba_id": "",
            "phone_number_id": "",
            "business_phone": "",
            "has_token": False,
            "webhook_verify_token": "",
            "verified_at": None,
            "last_error": "",
            "templates": [],
        }
    templates = MessageTemplate.objects.for_tenant(connection.organization).filter(
        channel="whatsapp"
    )
    return {
        "mode": connection.mode,
        "status": connection.status,
        "waba_id": connection.waba_id,
        "phone_number_id": connection.phone_number_id,
        "business_phone": connection.business_phone,
        "has_token": bool(connection.access_token),
        "webhook_verify_token": connection.webhook_verify_token,
        "verified_at": connection.verified_at,
        "last_error": connection.last_error,
        "templates": [
            {
                "event": row.event,
                "event_label": EVENTS[row.event].label if row.event in EVENTS else row.event,
                "language": row.language,
                "status": row.provider_status,
                "status_label": row.get_provider_status_display(),
                "rejection_reason": row.rejection_reason,
                "synced_at": row.synced_at,
            }
            for row in templates.order_by("event", "language")
        ],
    }


@api_view(["GET", "PUT"])
@permission_classes([IsOwner])
def whatsapp_connection(request, version=None):
    organization = request.user.organization
    connection = WhatsAppConnection.objects.for_tenant(organization).filter().first()
    if request.method == "PUT":
        connection = connection or WhatsAppConnection(organization=organization)
        mode = request.data.get("mode", connection.mode or "console")
        if mode not in WhatsAppConnection.Mode.values:
            return Response({"mode": ["Неизвестный режим."]}, status=400)
        connection.mode = mode
        for field in ("waba_id", "phone_number_id", "business_phone"):
            value = request.data.get(field, getattr(connection, field))
            setattr(connection, field, str(value).strip())
        if "access_token" in request.data and request.data["access_token"]:
            connection.access_token = str(request.data["access_token"]).strip()
        if not connection.webhook_verify_token:
            connection.webhook_verify_token = new_verify_token()
        connection.status = WhatsAppConnection.Status.DISCONNECTED
        connection.last_error = ""
        connection.save()
    return Response(_connection_payload(connection))


@api_view(["POST"])
@permission_classes([IsOwner])
def whatsapp_test(request, version=None):
    connection = WhatsAppConnection.objects.for_tenant(request.user.organization).filter().first()
    if not connection:
        return Response({"detail": "Сначала сохраните подключение."}, status=400)
    try:
        result = verify_connection(connection)
        connection.status = WhatsAppConnection.Status.CONNECTED
        connection.verified_at = timezone.now()
        connection.last_error = ""
        connection.save(update_fields=["status", "verified_at", "last_error", "updated_at"])
        ensure_default_templates(connection)
    except WhatsAppError as exc:
        connection.status = WhatsAppConnection.Status.ERROR
        connection.last_error = str(exc)
        connection.save(update_fields=["status", "last_error", "updated_at"])
        return Response({"detail": str(exc)}, status=400)
    return Response({**_connection_payload(connection), "provider": result})


@api_view(["POST"])
@permission_classes([IsOwner])
def whatsapp_sync_templates(request, version=None):
    connection = WhatsAppConnection.objects.for_tenant(request.user.organization).filter().first()
    if not connection or connection.status != WhatsAppConnection.Status.CONNECTED:
        return Response({"detail": "WhatsApp не подключён."}, status=400)
    try:
        ensure_default_templates(connection)
    except WhatsAppError as exc:
        return Response({"detail": str(exc)}, status=400)
    return Response(_connection_payload(connection))


@api_view(["GET", "POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def whatsapp_webhook(request, version=None):
    if request.method == "GET":
        token = request.query_params.get("hub.verify_token", "")
        challenge = request.query_params.get("hub.challenge", "")
        if WhatsAppConnection.objects.filter(webhook_verify_token=token).exists():
            return HttpResponse(challenge)
        return HttpResponse("invalid verify token", status=403)
    if not valid_webhook_signature(request.body, request.headers.get("X-Hub-Signature-256", "")):
        return JsonResponse({"detail": "invalid signature"}, status=403)
    handle_webhook(request.data)
    return JsonResponse({"ok": True})


def _reply_state(parent):
    connection = WhatsAppConnection.objects.for_tenant(parent.organization).first()
    if not connection or connection.status != WhatsAppConnection.Status.CONNECTED:
        return False, "WhatsApp центра не подключён"
    recipient, reason = CHANNELS["whatsapp"].recipient(parent)
    if not recipient:
        return False, reason
    if service.consent_status(parent, MessageCategory.UTILITY) != MessagingConsent.Status.OPTED_IN:
        return False, "Нет согласия на служебные сообщения"
    if not within_service_window(parent):
        return False, "24-часовое окно ответа закрыто — используйте одобренный шаблон Meta"
    return True, ""


@api_view(["POST"])
@permission_classes([IsOwnerOrManagerOrAdmin])
def whatsapp_reply(request, version=None):
    parent = (
        ParentContact.objects.for_tenant(request.user.organization)
        .filter(pk=request.data.get("parent_id"))
        .first()
    )
    if parent is None:
        return Response({"detail": "Родитель не найден."}, status=404)
    available, reason = _reply_state(parent)
    if not available:
        return Response({"detail": reason}, status=400)
    try:
        message = service.notify_whatsapp_reply(
            parent, request.data.get("body", ""), user=request.user
        )
    except service.MessagingError as exc:
        return Response({"detail": str(exc)}, status=400)
    return Response(_message_row(message), status=202)


def _bulk_candidates(organization, source, ids):
    from domains.money.subscriptions.debt import debtor_subscriptions
    from domains.money.subscriptions.models import Subscription

    if source not in {"debts", "renewals"}:
        raise ValueError("Неизвестный список.")
    if source == "debts":
        subscriptions = list(debtor_subscriptions(organization).filter(pk__in=ids)[:200])
    else:
        subscriptions = list(
            Subscription.objects.for_tenant(organization)
            .filter(pk__in=ids)
            .select_related("child")[:200]
        )
    links = (
        ChildContact.objects.for_tenant(organization)
        .filter(child_id__in=[s.child_id for s in subscriptions], is_payer=True)
        .select_related("parent_contact")
        .prefetch_related("parent_contact__phones")
    )
    payers = {link.child_id: link.parent_contact for link in links}
    event = "payment_due" if source == "debts" else "subscription_ending"
    result = []
    for subscription in subscriptions:
        parent = payers.get(subscription.child_id)
        context = {"child": subscription.child.full_name}
        if source == "debts":
            context["amount"] = f"{int(subscription.debt):,} ₸".replace(",", " ")
        else:
            remaining = subscription.sessions_remaining_cache
            context["left"] = (
                f"{remaining} занятий"
                if remaining is not None
                else f"до {subscription.ends_on:%d.%m.%Y}"
            )
        result.append((subscription, parent, event, context))
    return result


@api_view(["POST"])
@permission_classes([IsOwnerOrManagerOrAdmin])
def whatsapp_bulk(request, version=None):
    source = request.data.get("source")
    ids = request.data.get("ids") or []
    if not isinstance(ids, list) or not ids or len(ids) > 200:
        return Response({"detail": "Выберите от 1 до 200 строк."}, status=400)
    try:
        candidates = _bulk_candidates(request.user.organization, source, ids)
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=400)
    preview = request.data.get("preview", True)
    rows, queued = [], 0
    templates = {}
    today = timezone.localdate().isoformat()
    for subscription, parent, event, context in candidates:
        reason = ""
        language = service.parent_language(parent) if parent else "ru"
        template = (
            MessageTemplate.objects.for_tenant(request.user.organization)
            .filter(event=event, channel="whatsapp", language=language)
            .first()
        )
        subject, body = service.template_for(request.user.organization, event, "whatsapp", language)
        values = {
            "parent": service._first_name(parent.full_name) if parent else "",
            "center": request.user.organization.name,
            **context,
        }
        rendered_body = service.render(body, values)
        template_preview = {
            "name": template_name(event, language),
            "event": event,
            "event_label": EVENTS[event].label,
            "language": language,
            "body": rendered_body,
        }
        templates[(event, language)] = template_preview
        recipient = ""
        if not parent:
            reason = "Не указан плательщик"
        else:
            raw_phone = parent.whatsapp or parent.phones.values_list("number", flat=True).first()
            if not raw_phone:
                reason = "Нет номера WhatsApp"
            else:
                try:
                    recipient = normalize_phone_number(raw_phone)
                except InvalidPhoneNumberError:
                    reason = "Некорректный номер WhatsApp"
        consent = service.consent_status(parent, EVENTS[event].category) if parent else None
        if not reason and consent == MessagingConsent.Status.OPTED_OUT:
            reason = "Родитель отписался"
        elif not reason and consent != MessagingConsent.Status.OPTED_IN:
            reason = "Нет согласия на служебные сообщения"
        if not reason and (
            not template or template.provider_status != MessageTemplate.ProviderStatus.APPROVED
        ):
            reason = "Шаблон Meta ещё не одобрен"
        dedup_key = f"whatsapp:{event}:{subscription.id}:{today}"
        existing = (
            OutboundMessage.objects.for_tenant(request.user.organization)
            .filter(dedup_key=dedup_key)
            .first()
        )
        if not reason and existing:
            reason = "Такое напоминание уже поставлено сегодня"
        service_window = within_service_window(parent) if parent else False
        row = {
            "subscription_id": str(subscription.id),
            "child": subscription.child.full_name,
            "parent": parent.full_name if parent else "",
            "ready": not reason,
            "reason": reason,
            "service_window": service_window,
            "template": template_preview,
            "mode": ("Свободный текст доступен" if service_window else "Только одобренный шаблон"),
        }
        rows.append(row)
        if preview or not parent:
            continue
        if not reason:
            message = service.notify(
                parent,
                event,
                {**context, "_channel": "whatsapp"},
                dedup_key=dedup_key,
                user=request.user,
            )
            if message.status == OutboundMessage.Status.QUEUED:
                queued += 1
            continue
        if existing:
            continue
        skipped_status = OutboundMessage.Status.FAILED
        if consent == MessagingConsent.Status.OPTED_OUT:
            skipped_status = OutboundMessage.Status.OPTED_OUT
        elif consent != MessagingConsent.Status.OPTED_IN:
            skipped_status = OutboundMessage.Status.NO_CONSENT
        elif not recipient:
            skipped_status = OutboundMessage.Status.NO_CHANNEL
        OutboundMessage.objects.create(
            organization=request.user.organization,
            parent=parent,
            event=event,
            category=EVENTS[event].category,
            dedup_key=dedup_key,
            context={k: str(v) for k, v in context.items()},
            status=skipped_status,
            channel="whatsapp",
            recipient=recipient,
            language=language,
            subject=service.render(subject, values)[:200],
            body=rendered_body,
            attempts=[{"channel": "whatsapp", "result": "skipped", "reason": reason}],
            error=reason,
            created_by=request.user,
        )
    return Response(
        {
            "total": len(rows),
            "ready": sum(row["ready"] for row in rows),
            "queued": queued,
            "templates": list(templates.values()),
            "results": rows,
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
        "event_label": (
            EVENTS[m.event].label
            if m.event in EVENTS
            else "Ответ в WhatsApp"
            if m.event == "whatsapp_reply"
            else m.event
        ),
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
    reply = None
    if params.get("parent"):
        parent = (
            ParentContact.objects.for_tenant(request.user.organization)
            .filter(pk=params["parent"])
            .first()
        )
        rows = rows.filter(parent_id=params["parent"])
        if parent:
            available, reason = _reply_state(parent)
            reply = {
                "parent_id": str(parent.id),
                "parent_name": parent.full_name,
                "available": available,
                "reason": reason,
            }
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
            "whatsapp_reply": reply,
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
