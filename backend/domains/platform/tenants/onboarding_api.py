"""
API мастера онбординга для frontend2 (TRU-86) — тонкая обёртка над
onboarding.py, как и веб-вьюхи (onboarding_views.py). Мастер сам ничего не
создаёт: шаги засчитываются по данным, которые пишут обычные экраны
(филиалы, направления, группы, импорт). Только владелец.
"""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from domains.platform.core.permissions import IsOwner

from . import onboarding


def _payload(organization):
    steps = onboarding.get_steps(organization)
    return {
        "steps": [
            {"key": step.key, "title": onboarding.STEP_TITLES[step.key], "status": step.status}
            for step in steps
        ],
        "current": onboarding.current_step(organization),
        "done": sum(1 for step in steps if step.done),
        "total": len(steps),
        "finished": onboarding.is_finished(organization),
    }


@api_view(["GET"])
@permission_classes([IsOwner])
def onboarding_state(request):
    return Response(_payload(request.user.organization))


@api_view(["POST"])
@permission_classes([IsOwner])
def onboarding_skip(request, step):
    if step not in onboarding.STEP_ORDER:
        return Response({"detail": "Нет такого шага."}, status=status.HTTP_404_NOT_FOUND)
    onboarding.skip_step(request.user.organization, step)
    return Response(_payload(request.user.organization))


@api_view(["POST"])
@permission_classes([IsOwner])
def onboarding_confirm_organization(request):
    """Шаг «Организация» — у неё всегда есть значения по умолчанию, поэтому
    «всё верно, дальше» без изменений тоже его проходит."""
    onboarding.confirm_organization(request.user.organization)
    return Response(_payload(request.user.organization))


@api_view(["POST"])
@permission_classes([IsOwner])
def onboarding_finish(request):
    onboarding.finish(request.user.organization)
    return Response(_payload(request.user.organization))
