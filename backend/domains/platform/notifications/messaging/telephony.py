"""Provider-neutral telephony workflow (TRU-174).

Zadarma is the first production adapter. ``console`` keeps local development
and CI usable without external credentials; callers always receive a ``tel:``
fallback when the PBX cannot start a call.
"""

import base64
import datetime
import hashlib
import hmac
import json
import secrets
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from domains.people.clients.models import ChildContact, CommunicationLog, ParentContact
from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number
from domains.platform.leads.models import Lead, LeadSource
from domains.platform.leads.services import create_lead
from domains.platform.tasks.models import Task
from domains.platform.tasks.services import create_task
from domains.platform.users.models import User

from ..models import CallRecord, TelephonyConnection


class TelephonyError(ValueError):
    pass


ZADARMA_API_URL = "https://api.zadarma.com"


def _zadarma_query(params):
    return urlencode(sorted((key, str(value)) for key, value in params.items() if value != ""))


def zadarma_signature(method, params, secret):
    """Return the signature described by the public Zadarma API contract."""

    query = _zadarma_query(params)
    md5 = hashlib.md5(query.encode()).hexdigest()
    digest = hmac.new(
        secret.encode(),
        f"{method}{query}{md5}".encode(),
        hashlib.sha1,
    ).digest()
    return base64.b64encode(digest).decode()


def _zadarma_request(connection, method, params, timeout=5):
    query = _zadarma_query(params)
    request = Request(
        f"{ZADARMA_API_URL}{method}?{query}",
        headers={
            "Authorization": (
                f"{connection.api_key}:"
                f"{zadarma_signature(method, params, connection.api_secret)}"
            )
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed provider host
            result = json.loads(response.read().decode())
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise TelephonyError("Zadarma недоступна. Звонок открыт на устройстве.") from exc
    if result.get("status") != "success":
        raise TelephonyError(str(result.get("message") or "Zadarma отклонила запрос."))
    return result


def _webhook_signature_source(payload):
    event = str(payload.get("event", "")).upper()
    if event in {"NOTIFY_OUT_START", "NOTIFY_OUT_END"}:
        fields = ("internal", "destination", "call_start")
    if event == "NOTIFY_ANSWER":
        fields = ("caller_id", "destination", "call_start")
    elif event in {"NOTIFY_START", "NOTIFY_INTERNAL", "NOTIFY_END"}:
        fields = ("caller_id", "called_did", "call_start")
    elif event not in {"NOTIFY_OUT_START", "NOTIFY_OUT_END"}:
        return ""
    return "".join(str(payload.get(field, "")) for field in fields)


def valid_zadarma_webhook_signature(payload, signature, secret):
    source = _webhook_signature_source(payload)
    if not source or not signature:
        return False
    expected = base64.b64encode(
        hmac.new(secret.encode(), source.encode(), hashlib.sha1).digest()
    ).decode()
    return hmac.compare_digest(expected, signature)


def _provider_datetime(value):
    if not value:
        return None
    parsed = parse_datetime(str(value).replace(" ", "T", 1))
    if parsed and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def zadarma_event_payload(payload, existing=None):
    """Translate Zadarma PBX notifications to the provider-neutral event contract."""

    event = str(payload.get("event", "")).upper()
    outbound = event.startswith("NOTIFY_OUT")
    direction = (
        CallRecord.Direction.OUTBOUND
        if outbound
        else (
            existing.direction
            if existing and event == "NOTIFY_ANSWER"
            else CallRecord.Direction.INBOUND
        )
    )
    disposition = str(payload.get("disposition", "")).lower()
    if event.endswith("_START") or event == "NOTIFY_INTERNAL":
        status = CallRecord.Status.RINGING
    elif event == "NOTIFY_ANSWER":
        status = CallRecord.Status.ANSWERED
    elif event in {"NOTIFY_END", "NOTIFY_OUT_END"}:
        answered = (
            disposition in {"answered", "answer", "completed"}
            or int(payload.get("duration") or 0) > 0
        )
        status = (
            CallRecord.Status.COMPLETED
            if answered
            else (CallRecord.Status.FAILED if outbound else CallRecord.Status.MISSED)
        )
    else:
        raise TelephonyError("Неизвестное событие Zadarma.")
    phone = (
        payload.get("destination")
        if direction == CallRecord.Direction.OUTBOUND
        else payload.get("caller_id")
    )
    return {
        "call_id": payload.get("pbx_call_id"),
        "phone": phone,
        "direction": direction,
        "status": status,
        "started_at": _provider_datetime(payload.get("call_start")),
        "ended_at": timezone.now() if event.endswith("_END") else None,
        "duration_seconds": int(payload.get("duration") or 0),
        "result": str(payload.get("disposition") or "")[:255],
    }


def normalize_phone(value):
    try:
        return normalize_phone_number(value)
    except InvalidPhoneNumberError as exc:
        raise TelephonyError("Укажите корректный номер телефона.") from exc


def connection_for(organization):
    connection, _ = TelephonyConnection.objects.get_or_create(organization=organization)
    if not connection.webhook_secret:
        connection.webhook_secret = secrets.token_urlsafe(32)
        connection.save(update_fields=["webhook_secret", "updated_at"])
    return connection


def resolve_phone(organization, phone):
    phone = normalize_phone(phone)
    parent = (
        ParentContact.objects.for_tenant(organization)
        .filter(phones__number=phone)
        .distinct()
        .first()
        or ParentContact.objects.for_tenant(organization).filter(whatsapp=phone).first()
    )
    child = None
    if parent:
        links = list(
            ChildContact.objects.for_tenant(organization)
            .filter(parent_contact=parent)
            .select_related("child")
            .order_by("-is_primary_contact", "created_at")[:2]
        )
        # A family phone shared by several children must open the parent card.
        child = links[0].child if len(links) == 1 else None
    lead = (
        Lead.objects.for_tenant(organization)
        .filter(phone=phone, deleted_at__isnull=True)
        .order_by("-created_at")
        .first()
    )
    return {"phone": phone, "parent": parent, "child": child, "lead": lead}


def _default_employee(organization):
    return (
        User.objects.filter(
            organization=organization,
            is_active=True,
            role__in=[User.Role.OWNER, User.Role.MANAGER, User.Role.ADMIN],
        )
        .order_by("role", "full_name")
        .first()
    )


def _write_communication(call):
    if call.communication_log_id or not call.child_id:
        return
    author = call.employee or _default_employee(call.organization)
    if not author:
        return
    note = (
        f"{call.get_direction_display()} звонок: {call.get_status_display()}, "
        f"{call.duration_seconds} сек."
    )
    if call.result:
        note += f" Результат: {call.result}"
    call.communication_log = CommunicationLog.objects.create(
        organization=call.organization,
        child=call.child,
        parent_contact=call.parent,
        channel=CommunicationLog.Channel.CALL,
        note=note,
        author=author,
    )
    call.save(update_fields=["communication_log", "updated_at"])


def _create_missed_task(call):
    assignee = call.employee or _default_employee(call.organization)
    source_key = f"missed_call:{call.phone}"
    existing = (
        Task.objects.for_tenant(call.organization)
        .filter(
            type=Task.Type.CALL_BACK,
            status=Task.Status.OPEN,
            source_key=source_key,
        )
        .first()
    )
    if existing:
        return existing
    return create_task(
        type=Task.Type.CALL_BACK,
        assignee=assignee,
        due_date=timezone.now() + datetime.timedelta(hours=1),
        subject=f"Перезвонить: пропущенный звонок {call.phone}",
        organization=call.organization,
        source=Task.Source.AUTO,
        lead=call.lead,
        child=call.child,
        description="Автоматически создано по пропущенному входящему звонку.",
        source_key=source_key,
    )


@transaction.atomic
def record_event(organization, payload):
    provider_call_id = str(payload.get("call_id") or payload.get("pbx_call_id") or "").strip()
    if not provider_call_id:
        raise TelephonyError("Провайдер не передал идентификатор звонка.")
    direction = payload.get("direction", CallRecord.Direction.INBOUND)
    if direction not in CallRecord.Direction.values:
        raise TelephonyError("Неизвестное направление звонка.")
    existing = (
        CallRecord.objects.for_tenant(organization)
        .filter(provider_call_id=provider_call_id)
        .first()
    )
    if not existing and direction == CallRecord.Direction.OUTBOUND:
        recent_manual = (
            CallRecord.objects.for_tenant(organization)
            .filter(
                provider_call_id__startswith="manual-",
                direction=CallRecord.Direction.OUTBOUND,
                phone=normalize_phone(payload.get("phone", "")),
                started_at__gte=timezone.now() - datetime.timedelta(minutes=5),
            )
            .order_by("-started_at")
            .first()
        )
        if recent_manual:
            recent_manual.provider_call_id = provider_call_id
            recent_manual.save(update_fields=["provider_call_id", "updated_at"])
            existing = recent_manual
    phone = payload.get("phone") or (existing.phone if existing else "")
    resolved = resolve_phone(organization, phone)
    status = payload.get("status") or (existing.status if existing else CallRecord.Status.RINGING)
    if status not in CallRecord.Status.values:
        raise TelephonyError("Неизвестный статус звонка.")
    started_at = payload.get("started_at") or (existing.started_at if existing else timezone.now())
    employee = None
    if payload.get("employee_id"):
        try:
            employee = User.objects.filter(
                organization=organization,
                pk=payload["employee_id"],
                is_active=True,
            ).first()
        except (TypeError, ValueError, ValidationError):
            raise TelephonyError("Некорректный идентификатор сотрудника.") from None
    defaults = {
        "direction": direction,
        "status": status,
        "phone": resolved["phone"],
        "started_at": started_at,
        "answered_at": payload.get("answered_at") or (existing.answered_at if existing else None),
        "ended_at": payload.get("ended_at") or (existing.ended_at if existing else None),
        "duration_seconds": max(
            0,
            int(
                payload.get("duration_seconds")
                if "duration_seconds" in payload
                else (existing.duration_seconds if existing else 0)
            ),
        ),
        "result": str(
            payload.get("result") if "result" in payload else (existing.result if existing else "")
        )[:255],
        "recording_url": str(
            payload.get("recording_url")
            if "recording_url" in payload
            else (existing.recording_url if existing else "")
        )[:1000],
        "recording_expires_at": payload.get("recording_expires_at")
        or (existing.recording_expires_at if existing else None),
        "employee": employee or (existing.employee if existing else None),
        "parent": resolved["parent"],
        "child": resolved["child"],
        "lead": resolved["lead"],
    }
    call, _ = CallRecord.objects.update_or_create(
        organization=organization,
        provider_call_id=provider_call_id,
        defaults=defaults,
    )
    if status == CallRecord.Status.MISSED:
        _create_missed_task(call)
    if status in {
        CallRecord.Status.COMPLETED,
        CallRecord.Status.EXTERNAL,
        CallRecord.Status.MISSED,
        CallRecord.Status.FAILED,
    }:
        _write_communication(call)
    return call


def start_outgoing_call(*, organization, employee, phone):
    phone = normalize_phone(phone)
    connection = connection_for(organization)
    resolved = resolve_phone(organization, phone)
    call = CallRecord.objects.create(
        organization=organization,
        provider_call_id=f"manual-{uuid.uuid4()}",
        direction=CallRecord.Direction.OUTBOUND,
        status=CallRecord.Status.EXTERNAL,
        phone=phone,
        started_at=timezone.now(),
        result="Номер открыт на устройстве сотрудника",
        employee=employee,
        parent=resolved["parent"],
        child=resolved["child"],
        lead=resolved["lead"],
    )
    if connection.provider == TelephonyConnection.Provider.CONSOLE or not connection.api_key:
        _write_communication(call)
        return {
            "started": False,
            "phone": phone,
            "tel_url": f"tel:{phone}",
            "mode": "fallback",
            "call_id": str(call.id),
        }
    if (
        connection.provider == TelephonyConnection.Provider.ZADARMA
        and connection.api_secret
        and connection.virtual_number
    ):
        try:
            _zadarma_request(
                connection,
                "/v1/request/callback/",
                {
                    "from": connection.virtual_number.strip().lstrip("+"),
                    "to": phone.lstrip("+"),
                },
            )
        except TelephonyError as exc:
            connection.status = TelephonyConnection.Status.ERROR
            connection.last_error = str(exc)[:500]
            connection.save(update_fields=["status", "last_error", "updated_at"])
            _write_communication(call)
            return {
                "started": False,
                "phone": phone,
                "tel_url": f"tel:{phone}",
                "mode": "fallback",
                "call_id": str(call.id),
                "message": str(exc),
            }
        connection.status = TelephonyConnection.Status.CONNECTED
        connection.last_error = ""
        connection.verified_at = timezone.now()
        connection.save(update_fields=["status", "last_error", "verified_at", "updated_at"])
        call.status = CallRecord.Status.RINGING
        call.result = "Callback передан в Zadarma"
        call.save(update_fields=["status", "result", "updated_at"])
        return {
            "started": True,
            "phone": phone,
            "mode": "zadarma",
            "call_id": str(call.id),
        }
    _write_communication(call)
    return {
        "started": False,
        "phone": phone,
        "tel_url": f"tel:{phone}",
        "mode": "fallback",
        "call_id": str(call.id),
        "message": "АТС недоступна — номер открыт в телефоне.",
    }


@transaction.atomic
def promote_unknown_call(call, actor):
    if call.organization_id != actor.organization_id:
        raise TelephonyError("Звонок другой организации.")
    if call.lead_id:
        return call.lead
    source, _ = LeadSource.objects.get_or_create(
        organization=actor.organization,
        name="Звонок",
        defaults={"is_active": True},
    )
    lead = create_lead(
        organization=actor.organization,
        actor=actor,
        parent_name=f"Звонок {call.phone}",
        phone=call.phone,
        source=source,
        assigned_to=actor,
    )
    call.lead = lead
    call.save(update_fields=["lead", "updated_at"])
    return lead


def new_webhook_secret():
    return secrets.token_urlsafe(32)
