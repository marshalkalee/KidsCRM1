from celery import shared_task
from django.utils import timezone


@shared_task
def deliver_message(message_id: str):
    from .service import deliver

    message = deliver(message_id)
    return {"id": str(message.id), "status": message.status}


@shared_task
def dispatch_parent_notifications():
    from .automation import dispatch_daily

    return {"queued": dispatch_daily()}


@shared_task
def dispatch_lesson_change_notification(lesson_id: str):
    from .automation import dispatch_lesson_change

    return {"queued": dispatch_lesson_change(lesson_id)}


@shared_task
def process_whatsapp_webhook(payload: dict):
    """Meta must receive 200 quickly; parsing and CRM writes happen in the worker."""
    from .whatsapp import handle_webhook

    return {"changed": handle_webhook(payload)}


@shared_task
def send_manual_whatsapp_task(message_id: str):
    from .service import deliver_manual

    message = deliver_manual(message_id)
    return {"id": str(message.id), "status": message.status}


@shared_task
def process_evolution_webhook(connection_id: str, payload: dict):
    """Evolution ждёт ответа на вебхук недолго; разбор — в воркере."""
    from .whatsapp import handle_evolution_webhook

    return {"changed": handle_evolution_webhook(connection_id, payload)}


@shared_task
def sync_evolution_states():
    """Сверить статусы номеров с сервером Evolution: вебхук об отключении мог
    не дойти, а отправка на отвалившийся номер — потерянное сообщение."""
    from ..models import WhatsAppConnection
    from .evolution import EvolutionError, connection_state, ensure_webhook, is_configured
    from .whatsapp import handle_evolution_webhook

    if not is_configured():
        return {"checked": 0}
    rows = WhatsAppConnection.objects.filter(
        deleted_at__isnull=True,
        mode=WhatsAppConnection.Mode.EVOLUTION,
        status__in=[WhatsAppConnection.Status.CONNECTED, WhatsAppConnection.Status.CONNECTING],
    ).exclude(instance_name="")
    checked = 0
    for connection in rows:
        try:
            state = connection_state(connection)
        except EvolutionError:
            continue  # сервер недоступен — не делаем выводов о номере
        expected = (
            "open" if connection.status == WhatsAppConnection.Status.CONNECTED else "connecting"
        )
        if state != expected:
            handle_evolution_webhook(
                connection.pk, {"event": "connection.update", "data": {"state": state}}
            )
        # Настройки вебхука на сервере Evolution — как в CRM (адрес, события, файлы).
        try:
            ensure_webhook(connection)
        except EvolutionError:
            pass
        checked += 1
    return {"checked": checked}


@shared_task
def process_instagram_webhook(payload: dict):
    """Acknowledge Meta quickly and route Direct/comments in the worker."""
    from .instagram import handle_webhook

    return {"changed": handle_webhook(payload)}


@shared_task
def create_unanswered_whatsapp_tasks():
    """Create one callback task for every inbound message left unanswered."""
    from datetime import timedelta

    from django.db.models import Q

    from domains.platform.tasks.models import Task
    from domains.platform.tenants.org_settings import (
        WHATSAPP_UNANSWERED_HOURS,
        get_org_setting,
    )

    from ..models import InboundWhatsAppMessage, OutboundMessage

    created = 0
    rows = InboundWhatsAppMessage.objects.filter(
        deleted_at__isnull=True,
        status=InboundWhatsAppMessage.Status.LINKED,
    ).select_related("organization", "parent", "child", "lead", "lead__assigned_to")
    now = timezone.now()
    for message in rows.iterator():
        hours = max(1, int(get_org_setting(message.organization, WHATSAPP_UNANSWERED_HOURS)))
        if message.created_at > now - timedelta(hours=hours):
            continue
        # Ответили — родителю, заявке или на этот номер (кнопка «WhatsApp»).
        answered = Q(lead_id=message.lead_id) if message.lead_id else Q(pk__in=[])
        if message.parent_id:
            answered |= Q(parent_id=message.parent_id)
        if message.sender_phone:
            answered |= Q(recipient=message.sender_phone, channel="whatsapp")
        if (
            OutboundMessage.objects.filter(
                organization=message.organization, created_at__gt=message.created_at
            )
            .filter(answered)
            .exists()
        ):
            continue
        owner = (
            message.organization.users.filter(is_active=True, role="owner")
            .order_by("created_at")
            .first()
        )
        _task, was_created = Task.objects.get_or_create(
            organization=message.organization,
            type=Task.Type.CALL_BACK,
            source_key=f"whatsapp-inbound:{message.id}",
            status=Task.Status.OPEN,
            defaults={
                "source": Task.Source.AUTO,
                "title": "Ответить на входящее сообщение WhatsApp",
                "description": (
                    f"{message.sender_phone}: "
                    f"{(message.text or f'[{message.message_type}]')[:350]}"
                ),
                "assigned_to": getattr(message.lead, "assigned_to", None) or owner,
                "lead": message.lead,
                "child": message.child,
                "due_at": now,
            },
        )
        created += int(was_created)
    return {"created": created}
