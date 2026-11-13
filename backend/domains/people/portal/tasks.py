from celery import shared_task


@shared_task
def notify_announcement(announcement_id: str):
    """Опубликованное объявление — семьям в WhatsApp, push или email."""
    from .announcements import notify_parents
    from .models import Announcement

    announcement = (
        Announcement.objects.filter(pk=announcement_id).select_related("organization").first()
    )
    return {"notified": notify_parents(announcement) if announcement else 0}
