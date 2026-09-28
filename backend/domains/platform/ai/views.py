from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from domains.platform.leads.services import visible_leads
from domains.platform.leads.views import CanManageLeads

from . import services


class AIThrottle(UserRateThrottle):
    """Каждый вызов стоит денег — ограничим частоту на сотрудника."""

    rate = "30/min"


@api_view(["GET"])
@permission_classes([CanManageLeads])
def ai_status(request, version=None):
    """Показывать ли ИИ-кнопки: без ключа их нет."""
    return Response({"enabled": services.is_enabled(), "goals": list(services.GOALS)})


@api_view(["POST"])
@permission_classes([CanManageLeads])
@throttle_classes([AIThrottle])
def lead_from_text(request, version=None):
    try:
        fields = services.lead_from_text(request.user.organization, request.data.get("text", ""))
    except services.AIError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(fields)


@api_view(["POST"])
@permission_classes([CanManageLeads])
@throttle_classes([AIThrottle])
def lead_message(request, lead_id, version=None):
    lead = (
        visible_leads(request.user)
        .select_related("organization", "direction", "branch")
        .filter(pk=lead_id)
        .first()
    )
    if lead is None:
        return Response({"detail": "Заявка не найдена."}, status=status.HTTP_404_NOT_FOUND)
    try:
        text = services.lead_message(
            lead,
            goal=request.data.get("goal", ""),
            language=request.data.get("language", "ru"),
            note=request.data.get("note", ""),
        )
    except services.AIError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"text": text})
