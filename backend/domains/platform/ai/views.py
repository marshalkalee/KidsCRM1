import base64

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from domains.platform.core.permissions import IsOwnerOrManagerOrAdmin, IsStaffOfOrganization
from domains.platform.core.role_permissions import can_use_ai_chat
from domains.platform.leads.services import visible_leads
from domains.platform.leads.views import CanManageLeads

from . import assist, chat, services


def _uuid_list(value):
    import uuid

    try:
        return [uuid.UUID(str(value))]
    except ValueError:
        return []


class CanUseAIChat(IsStaffOfOrganization):
    message = "Чат с ИИ доступен владельцу, управляющему и администратору."

    def has_permission(self, request, view):
        return super().has_permission(request, view) and can_use_ai_chat(request.user)


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
        result = services.clean_import_file(request.user.organization, request.FILES.get("file"))
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


def _ai(call):
    """Ошибка ИИ — 400 с текстом для пользователя."""
    try:
        return Response(call())
    except services.AIError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@permission_classes([IsOwnerOrManagerOrAdmin])
@throttle_classes([AIThrottle])
def reminders(request, version=None):
    """Напоминания о долге или продлении пачкой: {children: [id], kind, language}."""
    import uuid

    ids = []
    for value in request.data.get("children") or []:
        try:
            ids.append(uuid.UUID(str(value)))
        except ValueError:
            continue
    return _ai(
        lambda: {
            "items": assist.reminders(
                request.user,
                ids,
                kind=request.data.get("kind", ""),
                language=request.data.get("language", "ru"),
            )
        }
    )


@api_view(["POST"])
@permission_classes([IsStaffOfOrganization])
@throttle_classes([AIThrottle])
def communication_note(request, version=None):
    return _ai(
        lambda: assist.communication_note(request.user.organization, request.data.get("text", ""))
    )


@api_view(["POST"])
@permission_classes([IsStaffOfOrganization])
@throttle_classes([AIThrottle])
def child_brief(request, child_id, version=None):
    from domains.people.clients.models import Child

    child = Child.objects.for_tenant(request.user.organization).filter(pk=child_id).first()
    if child is None:
        return Response({"detail": "Ребёнок не найден."}, status=status.HTTP_404_NOT_FOUND)
    return _ai(lambda: assist.child_brief(child, request.user))


@api_view(["POST"])
@permission_classes([CanManageLeads])
@throttle_classes([AIThrottle])
def lead_groups(request, lead_id, version=None):
    lead = (
        visible_leads(request.user).select_related("direction", "branch").filter(pk=lead_id).first()
    )
    if lead is None:
        return Response({"detail": "Заявка не найдена."}, status=status.HTTP_404_NOT_FOUND)
    return _ai(lambda: assist.lead_groups(lead))


@api_view(["POST"])
@permission_classes([IsStaffOfOrganization])
@throttle_classes([AIThrottle])
def daily_plan(request, version=None):
    return _ai(lambda: assist.daily_plan(request))


@api_view(["POST"])
@permission_classes([CanManageLeads])
@throttle_classes([AIThrottle])
def rejection_reason(request, version=None):
    kind = "renewal" if request.data.get("kind") == "renewal" else "new"
    return _ai(
        lambda: assist.rejection_reason(
            request.user.organization, text=request.data.get("text", ""), kind=kind
        )
    )


@api_view(["POST"])
@permission_classes([CanUseAIChat])
@throttle_classes([AIThrottle])
def chat_view(request, version=None):
    """Чат на главной: {message, conversation?} → {conversation, answer, sources}.
    Без conversation — новый чат. ИИ смотрит данные CRM с правами того,
    кто спрашивает (ai/chat.py); переписка сохраняется."""
    conversation = None
    conversation_id = request.data.get("conversation")
    if conversation_id:
        conversation = (
            chat.own_conversations(request.user).filter(pk__in=_uuid_list(conversation_id)).first()
        )
        if conversation is None:
            return Response({"detail": "Чат не найден."}, status=status.HTTP_404_NOT_FOUND)
    return _ai(
        lambda: chat.reply(
            request.user,
            question=str(request.data.get("message") or ""),
            conversation=conversation,
            host=request.get_host(),
        )
    )


@api_view(["GET"])
@permission_classes([CanUseAIChat])
def conversations(request, version=None):
    """История чатов сотрудника — последние 50, свежие сверху."""
    rows = chat.own_conversations(request.user)[:50]
    return Response([{"id": str(c.id), "title": c.title, "updated_at": c.updated_at} for c in rows])


@api_view(["GET", "DELETE"])
@permission_classes([CanUseAIChat])
def conversation_detail(request, conversation_id, version=None):
    conversation = chat.own_conversations(request.user).filter(pk=conversation_id).first()
    if conversation is None:
        return Response({"detail": "Чат не найден."}, status=status.HTTP_404_NOT_FOUND)
    if request.method == "DELETE":
        conversation.delete()  # soft delete — как везде в CRM
        return Response(status=status.HTTP_204_NO_CONTENT)
    return Response(
        {
            "id": str(conversation.id),
            "title": conversation.title,
            "updated_at": conversation.updated_at,
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "sources": m.sources,
                    "created_at": m.created_at,
                }
                for m in conversation.messages.all()
            ],
        }
    )
