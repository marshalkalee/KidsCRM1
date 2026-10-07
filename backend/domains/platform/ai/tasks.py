from celery import shared_task

from .generations import run


@shared_task
def run_ai_generation(generation_id: str):
    generation = run(generation_id)
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
