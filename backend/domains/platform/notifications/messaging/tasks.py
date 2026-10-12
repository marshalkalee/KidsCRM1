from celery import shared_task


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
