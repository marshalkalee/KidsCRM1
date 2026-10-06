from celery import shared_task

from .generations import run


@shared_task
def run_ai_generation(generation_id: str):
    generation = run(generation_id)
    return {"id": str(generation.id), "status": generation.status}
