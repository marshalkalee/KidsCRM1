from celery import shared_task


@shared_task
def deliver_message(message_id: str):
    from .service import deliver

    message = deliver(message_id)
    return {"id": str(message.id), "status": message.status}
