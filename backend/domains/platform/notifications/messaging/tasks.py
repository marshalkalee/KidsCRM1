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
def process_instagram_webhook(payload: dict):
    """Acknowledge Meta quickly and route Direct/comments in the worker."""
    from .instagram import handle_webhook

    return {"changed": handle_webhook(payload)}


@shared_task
def create_unanswered_whatsapp_tasks():
    """Create one callback task for every inbound message left unanswered."""
    from datetime import timedelta

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
        if (
            message.parent_id
            and OutboundMessage.objects.filter(
                organization=message.organization,
                parent=message.parent,
                created_at__gt=message.created_at,
            ).exists()
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
