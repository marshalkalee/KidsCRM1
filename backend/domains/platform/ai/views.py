import base64
import re

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from domains.platform.core.permissions import IsOwnerOrManagerOrAdmin, IsStaffOfOrganization
from domains.platform.core.role_permissions import can_use_ai_chat
from domains.platform.leads.services import visible_leads
from domains.platform.leads.views import CanManageLeads
from domains.platform.tenants.org_settings import (
    AI_ATTENDANCE_PHOTO_ENABLED,
    AI_IMPORT_CLEAN_ENABLED,
    get_org_setting,
)

from . import assist, chat, generations, recommendations, services
from .models import AIContentDraft, AIGeneration, AIRecommendationState


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


def _content_language(language, instructions):
    text = instructions.casefold()
    if any(
        phrase in text for phrase in ("на казахском", "казахский язык", "қазақша", "қазақ тілінде")
    ):
        return "kk"
    if any(phrase in text for phrase in ("на русском", "русский язык", "орысша", "орыс тілінде")):
        return "ru"
    return language


def _content_count(instructions):
    """Количество берём из пожелания; без него генерируем три варианта."""
    text = instructions.casefold()
    subject = r"(?:пост\w*|публикаци\w*|рилс\w*|reels|иде\w*|вариант\w*|штук\w*)"
    match = re.search(rf"\b(\d+)\s*{subject}", text)
    if match:
        return min(max(int(match.group(1)), 1), 5)
    words = {
        "один": 1,
        "одну": 1,
        "бір": 1,
        "два": 2,
        "две": 2,
        "екі": 2,
        "три": 3,
        "үш": 3,
        "четыре": 4,
        "төрт": 4,
        "пять": 5,
        "бес": 5,
    }
    for word, count in words.items():
        if re.search(rf"\b{word}\s+{subject}", text):
            return count
    return 3


class AIThrottle(UserRateThrottle):
    """Каждый вызов стоит денег — ограничим частоту на сотрудника."""

    rate = "30/min"


def _org_allows(request, key) -> bool:
    return bool(get_org_setting(request.user.organization, key))


# Центр не включил — функция отправила бы во внешнюю модель фото или файл
# как есть (ADR-0008); включает владелец в «Настройки → Доступ сотрудников».
OPT_IN_REQUIRED = (
    "Центр не включил эту функцию: владелец включает её в «Настройки → Доступ сотрудников»."
)


@api_view(["GET"])
@permission_classes([IsStaffOfOrganization])
def ai_status(request, version=None):
    """Показывать ли ИИ-кнопки: без ключа их нет; фото журнала и чистка
    импорта — ещё и только у центров, которые их включили."""
    enabled = services.is_enabled()
    return Response(
        {
            "enabled": enabled,
            "goals": list(services.GOALS),
            "attendance_photo": enabled and _org_allows(request, AI_ATTENDANCE_PHOTO_ENABLED),
            "import_clean": enabled and _org_allows(request, AI_IMPORT_CLEAN_ENABLED),
        }
    )


@api_view(["GET", "POST"])
@permission_classes([CanUseAIChat])
def group_recommendations(request, version=None):
    """Запуск не ждёт LLM; GET возвращает последнюю журнальную запись."""
    if request.method == "POST":
        generation = generations.enqueue(request.user.organization, "group_promotion")
        return Response({"id": str(generation.id), "status": generation.status}, status=202)
    generation = (
        AIGeneration.objects.for_tenant(request.user.organization)
        .filter(function="group_promotion")
        .first()
    )
    if generation is None:
        return Response({"generation": None, "recommendations": []})
    return Response(
        {
            "generation": {
                "id": str(generation.id),
                "status": generation.status,
                "created_at": generation.created_at,
                "error": generation.error_detail,
            },
            "recommendations": generation.result.get("recommendations", []),
        }
    )


@api_view(["POST"])
@permission_classes([CanUseAIChat])
def dismiss_recommendation(request, recommendation_id, version=None):
    try:
        state = recommendations.dismiss(request.user.organization, recommendation_id)
    except AIRecommendationState.DoesNotExist:
        return Response({"detail": "Рекомендация не найдена."}, status=404)
    return Response({"id": str(state.id), "status": state.status})


def _draft_data(draft):
    return {
        "id": str(draft.id),
        "title": draft.title,
        "language": draft.language,
        "payload": draft.payload,
        "updated_at": draft.updated_at,
    }


def _generation_history_data(generation):
    return {
        "id": str(generation.id),
        "created_at": generation.created_at,
        "language": generation.result.get("language")
        or generation.parameters.get("language", "ru"),
        "content_type": generation.result.get("content_type")
        or generation.parameters.get("content_type", "both"),
        "content_count": generation.result.get("content_count")
        or generation.parameters.get("content_count", 3),
        "instructions": generation.parameters.get("instructions", ""),
        "content": generation.result,
    }


@api_view(["GET", "POST"])
@permission_classes([CanUseAIChat])
def content_studio(request, version=None):
    """Запуск в фоне и последний готовый контент-блок организации."""
    organization = request.user.organization
    if request.method == "POST":
        language = request.data.get("language", "ru")
        instructions = str(request.data.get("instructions", "")).strip()
        language = _content_language(language, instructions)
        content_type = request.data.get("content_type", "both")
        content_count = _content_count(instructions)
        if language not in {"ru", "kk"}:
            return Response({"language": ["Поддерживаются русский и казахский."]}, status=400)
        if content_type not in {"post", "reel", "both"}:
            return Response({"content_type": ["Выберите формат результата."]}, status=400)
        if len(instructions) > 1000:
            return Response(
                {"instructions": ["Пожелания должны быть не длиннее 1000 символов."]},
                status=400,
            )
        generation = generations.enqueue(
            organization,
            "content_studio",
            {
                "language": language,
                "content_type": content_type,
                "content_count": content_count,
                "instructions": instructions,
            },
        )
        return Response({"id": str(generation.id), "status": generation.status}, status=202)
    generation = (
        AIGeneration.objects.for_tenant(organization).filter(function="content_studio").first()
    )
    history = AIGeneration.objects.for_tenant(organization).filter(
        function="content_studio",
        status=AIGeneration.Status.SUCCEEDED,
    )[:20]
    drafts = AIContentDraft.objects.for_tenant(organization)[:20]
    return Response(
        {
            "generation": (
                {
                    "id": str(generation.id),
                    "status": generation.status,
                    "created_at": generation.created_at,
                    "error": generation.error_detail,
                    "parameters": generation.parameters,
                }
                if generation
                else None
            ),
            "content": generation.result if generation else {},
            "history": [_generation_history_data(item) for item in history],
            "drafts": [_draft_data(draft) for draft in drafts],
        }
    )


@api_view(["POST"])
@permission_classes([CanUseAIChat])
def cancel_content_generation(request, generation_id, version=None):
    with transaction.atomic():
        generation = (
            AIGeneration.objects.select_for_update()
            .for_tenant(request.user.organization)
            .filter(pk=generation_id, function="content_studio")
            .first()
        )
        if generation is None:
            return Response({"detail": "Генерация не найдена."}, status=404)
        if generation.status not in {
            AIGeneration.Status.QUEUED,
            AIGeneration.Status.RUNNING,
        }:
            return Response({"detail": "Эта генерация уже завершена."}, status=409)
        generation.status = AIGeneration.Status.CANCELLED
        generation.finished_at = timezone.now()
        generation.error_code = "cancelled"
        generation.error_detail = "Генерация отменена пользователем."
        generation.save(
            update_fields=[
                "status",
                "finished_at",
                "error_code",
                "error_detail",
                "updated_at",
            ]
        )
    return Response({"id": str(generation.id), "status": generation.status})


@api_view(["POST"])
@permission_classes([CanUseAIChat])
def content_drafts(request, version=None):
    title = str(request.data.get("title", "")).strip()
    language = request.data.get("language", "ru")
    payload = request.data.get("payload")
    if len(title) < 3 or len(title) > 120:
        return Response({"title": ["Название должно содержать от 3 до 120 символов."]}, status=400)
    if language not in {"ru", "kk"}:
        return Response({"language": ["Выберите язык."]}, status=400)
    if not isinstance(payload, dict) or not payload:
        return Response({"payload": ["Нет контента для сохранения."]}, status=400)
    generation = None
    generation_id = request.data.get("generation")
    if generation_id:
        generation = (
            AIGeneration.objects.for_tenant(request.user.organization)
            .filter(pk=generation_id, function="content_studio")
            .first()
        )
    draft = AIContentDraft.objects.create(
        organization=request.user.organization,
        language=language,
        title=title,
        payload=payload,
        generation=generation,
        created_by=request.user,
    )
    return Response(_draft_data(draft), status=201)


@api_view(["PATCH", "DELETE"])
@permission_classes([CanUseAIChat])
def content_draft_detail(request, draft_id, version=None):
    draft = AIContentDraft.objects.for_tenant(request.user.organization).filter(pk=draft_id).first()
    if draft is None:
        return Response({"detail": "Вариант не найден."}, status=404)
    if request.method == "DELETE":
        draft.delete()
        return Response(status=204)
    title = str(request.data.get("title", draft.title)).strip()
    payload = request.data.get("payload", draft.payload)
    if len(title) < 3 or len(title) > 120:
        return Response({"title": ["Название должно содержать от 3 до 120 символов."]}, status=400)
    if not isinstance(payload, dict) or not payload:
        return Response({"payload": ["Нет контента для сохранения."]}, status=400)
    draft.title = title
    draft.payload = payload
    draft.save(update_fields=["title", "payload", "updated_at"])
    return Response(_draft_data(draft))


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

    if not _org_allows(request, AI_ATTENDANCE_PHOTO_ENABLED):
        return Response({"detail": OPT_IN_REQUIRED}, status=status.HTTP_403_FORBIDDEN)
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
    if not _org_allows(request, AI_IMPORT_CLEAN_ENABLED):
        return Response({"detail": OPT_IN_REQUIRED}, status=status.HTTP_403_FORBIDDEN)
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
