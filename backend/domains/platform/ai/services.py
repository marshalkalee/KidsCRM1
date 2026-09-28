# ruff: noqa: E501 — промпты: связный текст, резать строки ради длины хуже для чтения.
"""
ИИ-помощник (эксперимент, ветка experiment/ai-assistant — не в develop).

Две функции для продаж:
- lead_from_text — вставили сообщение из WhatsApp/Instagram, получили
  поля заявки: имя, телефон, ребёнок, возраст, направление, источник, суть;
- lead_message — готовое сообщение родителю под статус заявки, на
  русском или казахском, для отправки через wa.me вручную.

Модель отвечает строго по JSON-схеме (structured outputs), поэтому ответ
всегда разбирается. Без ANTHROPIC_API_KEY всё выключено (is_enabled).

Данные: в Claude уходит только то, что нужно для задачи. Для сообщения
родителю — имя, ребёнок, направление, статус, комментарии; телефон не
отправляем. Для разбора — сам вставленный текст (в нём обычно и есть
телефон — это и есть задача).
"""

import json
import logging

import anthropic
from django.conf import settings
from django.utils import timezone

from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number
from domains.platform.leads.models import Lead, LeadSource
from domains.platform.tenants.models import Direction

logger = logging.getLogger(__name__)

MAX_INPUT_CHARS = 4000
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AIError(Exception):
    """Сообщение для пользователя — показывается как есть."""


def is_enabled() -> bool:
    return bool(settings.ANTHROPIC_API_KEY)


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, timeout=60, max_retries=2)


def _ask_json(*, system: str, user: str, schema: dict, max_tokens: int = 4000) -> dict:
    """Один запрос, ответ строго по схеме. Короткие задачи — effort low:
    быстрее и дешевле, качества хватает. Отказ модели — fallbacks по
    умолчанию переигрывает запрос на подходящей модели на стороне API."""
    if not is_enabled():
        raise AIError("ИИ-помощник не настроен.")
    try:
        response = _client().beta.messages.create(
            model=settings.AI_MODEL,
            max_tokens=max_tokens,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        )
    except anthropic.RateLimitError as exc:
        logger.warning("AI rate limited: %s", exc)
        raise AIError("ИИ сейчас перегружен — попробуйте через минуту.") from exc
    except anthropic.APIStatusError as exc:
        logger.error("AI API error %s: %s", exc.status_code, exc.message)
        raise AIError("ИИ временно недоступен.") from exc
    except anthropic.APIConnectionError as exc:
        logger.error("AI connection error: %s", exc)
        raise AIError("Нет связи с ИИ — проверьте интернет.") from exc

    if response.stop_reason == "refusal":
        raise AIError("ИИ не стал обрабатывать этот текст.")
    if response.stop_reason == "max_tokens":
        raise AIError("Текст слишком длинный — сократите и попробуйте ещё раз.")
    text = next((block.text for block in response.content if block.type == "text"), "")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error("AI returned non-JSON (request %s)", getattr(response, "_request_id", "?"))
        raise AIError("ИИ ответил неразборчиво — попробуйте ещё раз.") from exc


# --- Заявка из сообщения --------------------------------------------------

LEAD_SYSTEM = """Ты помогаешь администратору детского центра (танцы, спорт, кружки) в Казахстане заводить заявки.
Тебе дают текст, который родитель прислал в WhatsApp, Instagram или который администратор записал со звонка.
Текст может быть на русском, казахском или смеси, с опечатками и сокращениями.

Извлеки поля заявки. Правила:
- parent_name — как обращаться к родителю (имя, можно с отчеством). Пусто, если не указано.
- phone — телефон как в тексте. Пусто, если нет.
- child_name — имя ребёнка. Пусто, если нет.
- child_age — возраст ребёнка полными годами. Если указан год или дата рождения — посчитай. 0, если неизвестно.
- direction — ровно одно значение из списка направлений центра, которое лучше всего подходит к запросу, или пустая строка, если не ясно. Не выдумывай названия.
- source — ровно одно значение из списка источников, если из текста понятно, откуда пришли (например «увидела в инстаграме»), иначе пустая строка.
- summary — коротко по-русски, что хотят и важные детали (удобные дни и время, опыт ребёнка, вопросы о цене). 1–2 предложения. Пусто, если добавить нечего.
Не придумывай того, чего нет в тексте."""


def _lead_schema(directions: list[str], sources: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "parent_name": {"type": "string"},
            "phone": {"type": "string"},
            "child_name": {"type": "string"},
            "child_age": {"type": "integer"},
            "direction": {"type": "string", "enum": [*directions, ""]},
            "source": {"type": "string", "enum": [*sources, ""]},
            "summary": {"type": "string"},
        },
        "required": [
            "parent_name",
            "phone",
            "child_name",
            "child_age",
            "direction",
            "source",
            "summary",
        ],
        "additionalProperties": False,
    }


def lead_from_text(organization, text: str) -> dict:
    """Поля для формы новой заявки. Направление и источник — id из справочников
    организации (модель выбирает только из них), телефон — нормализованный."""
    text = (text or "").strip()
    if not text:
        raise AIError("Вставьте текст сообщения.")
    if len(text) > MAX_INPUT_CHARS:
        raise AIError("Слишком длинный текст — вставьте только сообщение родителя.")
    directions = {
        d.name: d for d in Direction.objects.for_tenant(organization).filter(is_active=True)
    }
    sources = {
        s.name: s for s in LeadSource.objects.for_tenant(organization).filter(is_active=True)
    }
    lists = (
        f"Направления центра: {json.dumps(list(directions), ensure_ascii=False)}\n"
        f"Источники заявок: {json.dumps(list(sources), ensure_ascii=False)}"
    )
    data = _ask_json(
        system=LEAD_SYSTEM,
        user=f"{lists}\n\nТекст:\n<message>\n{text}\n</message>",
        schema=_lead_schema(list(directions), list(sources)),
    )
    phone = (data.get("phone") or "").strip()
    try:
        phone = normalize_phone_number(phone) if phone else ""
    except InvalidPhoneNumberError:
        pass  # оставим как есть — администратор поправит в форме
    age = data.get("child_age") or None
    direction = directions.get(data.get("direction") or "")
    source = sources.get(data.get("source") or "")
    return {
        "parent_name": (data.get("parent_name") or "").strip(),
        "phone": phone,
        "child_name": (data.get("child_name") or "").strip(),
        "child_age": age if age and 0 < age <= 25 else None,
        "direction": str(direction.id) if direction else None,
        "source": str(source.id) if source else None,
        "summary": (data.get("summary") or "").strip(),
    }


# --- Сообщение родителю ---------------------------------------------------

GOALS = {
    "first_contact": "первое сообщение после заявки: поздороваться, представиться, предложить подобрать группу и спросить удобное время для пробного занятия",
    "invite_trial": "пригласить на бесплатное или пробное занятие, предложить 2 варианта времени, если они известны из комментариев",
    "after_trial": "спросить, как ребёнку понравилось пробное занятие, и мягко предложить оформить абонемент",
    "thinking": "мягко напомнить о себе родителю, который взял паузу подумать: без давления, ответить на возможные сомнения",
    "renewal": "напомнить, что абонемент заканчивается, и предложить продлить, отметив успехи ребёнка, если о них есть данные",
}

LANGUAGES = {"ru": "русском", "kk": "казахском"}

MESSAGE_SYSTEM = """Ты пишешь сообщения родителям от имени администратора детского центра в Казахстане.
Сообщение уйдёт в WhatsApp, администратор его проверит и отправит сам.
Правила:
- Тепло, вежливо, по-человечески, без канцелярита и без давления. Обращение на «Вы».
- Коротко: 2–5 предложений, до 600 символов. Можно 1 уместный эмодзи, не больше.
- Используй только факты из данных о заявке. Не придумывай цены, скидки, расписание и обещания.
- Если чего-то не знаешь (например времени занятий) — спроси у родителя, а не выдумывай.
- Без подписи с именем администратора, если её нет в данных.
- Пиши только на указанном языке. Для казахского — естественный разговорный казахский."""


def lead_message(lead: Lead, *, goal: str, language: str, note: str = "") -> str:
    if goal not in GOALS:
        raise AIError("Неизвестная цель сообщения.")
    if language not in LANGUAGES:
        raise AIError("Неизвестный язык.")
    comments = list(lead.comments.order_by("-created_at").values_list("text", flat=True)[:5])
    facts = {
        "центр": lead.organization.name,
        "родитель": lead.parent_name,
        "ребёнок": lead.child_name or None,
        "возраст ребёнка": lead.child_age,
        "направление": lead.direction.name if lead.direction else None,
        "филиал": lead.branch.name if lead.branch else None,
        "статус заявки": lead.get_status_display(),
        "дней в статусе": max(0, (timezone.now() - lead.status_changed_at).days),
        "комментарии администратора (свежие первыми)": comments or None,
    }
    user = (
        f"Данные о заявке:\n{json.dumps(facts, ensure_ascii=False, indent=1)}\n\n"
        f"Цель сообщения: {GOALS[goal]}.\n"
        f"Язык: {LANGUAGES[language]}.\n"
        + (f"Пожелание администратора: {note.strip()[:500]}\n" if note.strip() else "")
    )
    data = _ask_json(
        system=MESSAGE_SYSTEM,
        user=user,
        schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
        max_tokens=2000,
    )
    text = (data.get("text") or "").strip()
    if not text:
        raise AIError("ИИ не смог составить сообщение — попробуйте ещё раз.")
    return text
