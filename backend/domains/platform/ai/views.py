import base64

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from domains.platform.core.permissions import IsOwnerOrManagerOrAdmin, IsStaffOfOrganization
from domains.platform.leads.services import visible_leads
from domains.platform.leads.views import CanManageLeads

from . import services


def _uuid_list(value):
    import uuid

    try:
        return [uuid.UUID(str(value))]
    except ValueError:
        return []


class AIThrottle(UserRateThrottle):
    """Каждый вызов стоит денег — ограничим частоту на сотрудника."""

    rate = "30/min"


@api_view(["GET"])
@permission_classes([IsStaffOfOrganization])
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


@api_view(["POST"])
@permission_classes([IsStaffOfOrganization])
@throttle_classes([AIThrottle])
def search(request, version=None):
    """Поиск обычным языком → адрес списка с нашими фильтрами."""
    try:
        return Response(services.search_to_filters(request.user, request.data.get("query", "")))
    except services.AIError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@permission_classes([IsStaffOfOrganization])
@throttle_classes([AIThrottle])
def attendance_from_photo(request, version=None):
    """Фото журнала → предлагаемые отметки. Доступ к занятию — как у экрана
    посещаемости (преподаватель — только свои); ничего не сохраняет."""
    from domains.platform.users.models import User
    from domains.scheduling.schedule.models import Lesson

    lesson_ids = _uuid_list(request.data.get("lesson"))
    lesson = (
        Lesson.objects.for_tenant(request.user.organization).filter(pk__in=lesson_ids).first()
        if lesson_ids
        else None
    )
    if lesson is None:
        return Response({"detail": "Занятие не найдено."}, status=status.HTTP_404_NOT_FOUND)
    if request.user.role == User.Role.TEACHER and lesson.teacher_id != request.user.id:
        return Response(
            {"detail": "Доступно только для своих занятий."}, status=status.HTTP_403_FORBIDDEN
        )
    participants = list(lesson.participants().order_by("full_name"))
    try:
        result = services.attendance_from_photo(lesson, participants, request.FILES.get("image"))
    except services.AIError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


@api_view(["POST"])
@permission_classes([IsOwnerOrManagerOrAdmin])
@throttle_classes([AIThrottle])
def import_clean(request, version=None):
    """«Грязный» файл → файл в формате шаблона (base64) и строки для просмотра.
    Дальше — обычный импорт: маппинг, сухой прогон, решения по дублям."""
    try:
        result = services.clean_import_file(request.FILES.get("file"))
    except services.AIError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(
        {
            "rows": result["rows"],
            "source_rows": result["source_rows"],
            "problems": result["problems"],
            "file": base64.b64encode(result["xlsx"]).decode(),
        }
    )
