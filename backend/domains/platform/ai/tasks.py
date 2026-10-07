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
