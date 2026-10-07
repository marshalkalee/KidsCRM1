from celery import shared_task
from django.utils import timezone

from .generations import run
from .models import AIGeneration


@shared_task
def run_ai_generation(generation_id: str):
    try:
        generation = run(generation_id)
    except Exception as exc:
        # Celery records the traceback, while the UI receives a terminal state
        # instead of polling a generation marked as running forever.
        AIGeneration.objects.filter(pk=generation_id).update(
            status=AIGeneration.Status.PROVIDER_UNAVAILABLE,
            finished_at=timezone.now(),
            error_code="internal_error",
            error_detail=str(exc)[:500],
        )
        raise
    return {"id": str(generation.id), "status": generation.status}


@shared_task
def build_ai_digest(digest_id: str):
    from .digest import build

    digest = build(digest_id)
    return {"id": str(digest.id), "status": digest.status}


@shared_task
def dispatch_ai_digests():
    """Раз в час: дайджест центрам, у которых наступили их день и час (TRU-163)."""
    from .digest import dispatch

    return {"started": dispatch()}
