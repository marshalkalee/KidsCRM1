# ruff: noqa: E501 — промпты: связный текст, резать строки ради длины хуже для чтения.
"""
ИИ-помощник (эксперимент, ветка experiment/ai-assistant — не в develop).

Две функции для продаж:
- lead_from_text — вставили сообщение из WhatsApp/Instagram, получили
  поля заявки: имя, телефон, ребёнок, возраст, направление, источник, суть;
- lead_message — готовое сообщение родителю под статус заявки, на
  русском или казахском, для отправки через wa.me вручную.

Модель отвечает строго по JSON-схеме (structured outputs), поэтому ответ
всегда разбирается. Провайдер — AI_PROVIDER: anthropic (Claude) или
openai; без ключа выбранного провайдера всё выключено (is_enabled).

Данные: в модель уходит только то, что нужно для задачи. Для сообщения
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


def provider() -> str:
    """Провайдер модели: anthropic (по умолчанию) или openai — для показа
    с имеющимся ключом. Переключается AI_PROVIDER, код экранов один."""
    return settings.AI_PROVIDER


def is_enabled() -> bool:
    if provider() == "openai":
        return bool(settings.OPENAI_API_KEY)
    return bool(settings.ANTHROPIC_API_KEY)


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, timeout=60, max_retries=2)


def _openai_client():
    import openai

    return openai.OpenAI(api_key=settings.OPENAI_API_KEY, timeout=60, max_retries=2)


def _ask_json(
    *,
    system: str,
    user: str,
    schema: dict,
    max_tokens: int = 4000,
    image: tuple[str, str] | None = None,
) -> dict:
    """Один запрос, ответ строго по JSON-схеме — у обоих провайдеров.
    image — (media_type, base64) для задач по фото."""
    if not is_enabled():
        raise AIError("ИИ-помощник не настроен.")
    ask = _ask_openai if provider() == "openai" else _ask_anthropic
    text = ask(system=system, user=user, schema=schema, max_tokens=max_tokens, image=image)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error("AI returned non-JSON (%s)", provider())
        raise AIError("ИИ ответил неразборчиво — попробуйте ещё раз.") from exc


def _anthropic_content(user, image):
    if image is None:
        return user
    media_type, data = image
    return [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}},
        {"type": "text", "text": user},
    ]


def _openai_content(user, image):
    if image is None:
        return user
    media_type, data = image
    return [
        {"type": "text", "text": user},
        # high — иначе журнал сжимается и мелкие отметки путаются между колонками.
        {
            "type": "image_url",
            "image_url": {"url": f"data:{media_type};base64,{data}", "detail": "high"},
        },
    ]


def _ask_anthropic(*, system, user, schema, max_tokens, image=None) -> str:
    """Claude: короткие задачи — effort low (быстрее и дешевле); отказ модели
    fallbacks по умолчанию переигрывает на подходящей модели на стороне API."""
    try:
        response = _client().beta.messages.create(
            model=settings.AI_MODEL,
            max_tokens=max_tokens,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            system=system,
            messages=[{"role": "user", "content": _anthropic_content(user, image)}],
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
    return next((block.text for block in response.content if block.type == "text"), "")


def _ask_openai(*, system, user, schema, max_tokens, image=None) -> str:
    """OpenAI: Chat Completions со strict json_schema — ответ строго по схеме."""
    import openai

    try:
        response = _openai_client().chat.completions.create(
            # Фото журнала mini читает с ошибками в колонках — для картинок модель сильнее.
            model=settings.OPENAI_VISION_MODEL if image else settings.OPENAI_MODEL,
            max_completion_tokens=max_tokens,
            # Разбор и фильтры должны быть предсказуемыми: одна фраза — один ответ.
            temperature=0,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": _openai_content(user, image)},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": schema, "strict": True},
            },
        )
    except openai.RateLimitError as exc:
        logger.warning("OpenAI rate limited: %s", exc)
        raise AIError("ИИ сейчас перегружен — попробуйте через минуту.") from exc
    except openai.AuthenticationError as exc:
        logger.error("OpenAI auth error: %s", exc)
        raise AIError("Ключ ИИ не подошёл — проверьте OPENAI_API_KEY.") from exc
    except openai.APIStatusError as exc:
        logger.error("OpenAI API error %s: %s", exc.status_code, exc)
        raise AIError("ИИ временно недоступен.") from exc
    except openai.APIConnectionError as exc:
        logger.error("OpenAI connection error: %s", exc)
        raise AIError("Нет связи с ИИ — проверьте интернет.") from exc

    choice = response.choices[0]
    if choice.message.refusal:
        raise AIError("ИИ не стал обрабатывать этот текст.")
    if choice.finish_reason == "length":
        raise AIError("Текст слишком длинный — сократите и попробуйте ещё раз.")
    return choice.message.content or ""


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
        # Сегодняшняя дата — иначе «2017 г.р.» превращается в неверный возраст.
        user=f"Сегодня: {timezone.localdate():%d.%m.%Y}\n{lists}\n\nТекст:\n<message>\n{text}\n</message>",
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
- Обращайся по имени родителя, без фамилии (если имя с отчеством — можно с отчеством).
- Не обещай «варианты», «предложения» или время, которых нет в данных, — вместо этого спроси, какое время удобно.
- Эмодзи — только нейтральный (🙂 или 🌸), без сердечек.
- Пиши только на указанном языке. Для казахского — естественный разговорный казахский, без дословного перевода с русского."""


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


# --- Поиск обычным языком ------------------------------------------------

SEARCH_SYSTEM = """Ты переводишь запрос сотрудника детского центра в фильтры CRM. Сам ничего не ищешь и данных не знаешь.
Экраны:
- children — список детей. Фильтры: branch, direction, group, child_status, has_debt (есть долг), debt_overdue (долг просрочен), expiring (абонемент скоро заканчивается), no_subscription (занимается без абонемента), text (поиск по имени).
- leads — заявки. Фильтры: branch, direction, lead_source, lead_kind (new — новые продажи, renewal — продления), only_mine (мои заявки), created_from/created_to (дата создания ГГГГ-ММ-ДД), text (имя или телефон).
Правила:
- Выбирай значения только из переданных списков. Не подходит ничего — пустая строка или false.
- «Должники», «долг» — has_debt. Долг «давно», «больше недели», «старше N дней», «просрочен» — ещё и debt_overdue.
- «Без абонемента», «не оплатили абонемент» — no_subscription; «абонемент заканчивается», «продлить» — expiring.
- Даты считай от сегодняшней: «за сентябрь», «за неделю», «вчера». Не про даты — пустые строки.
- text — только если в запросе есть конкретное имя или телефон.
- explanation — одна короткая фраза по-русски, что ты отфильтровал (например «Дети с просроченным долгом, филиал Орбита»)."""


def search_to_filters(user, query: str) -> dict:
    """Фраза → адрес экрана с нашими же фильтрами. ИИ выбирает только из
    справочников организации, данные остаются на сервере — ответ проверяемый:
    сотрудник видит обычный список с выставленными фильтрами."""
    from urllib.parse import urlencode

    from django.utils.dateparse import parse_date

    from domains.platform.core.role_permissions import can_manage_leads, can_view_client_money
    from domains.platform.tenants.models import Branch
    from domains.scheduling.groups.models import Group

    query = (query or "").strip()
    if not query:
        raise AIError("Напишите, что найти.")
    if len(query) > 300:
        raise AIError("Слишком длинный запрос.")
    organization = user.organization
    branches = {b.name: b for b in Branch.objects.for_tenant(organization).filter(is_active=True)}
    directions = {
        d.name: d for d in Direction.objects.for_tenant(organization).filter(is_active=True)
    }
    groups = {
        f"{g.name} ({g.branch.name})" if g.branch_id else g.name: g
        for g in Group.objects.for_tenant(organization).select_related("branch")
    }
    sources = {
        s.name: s for s in LeadSource.objects.for_tenant(organization).filter(is_active=True)
    }
    screens = ["children", *(["leads"] if can_manage_leads(user) else [])]

    def enum(values):
        return {"type": "string", "enum": [*values, ""]}

    schema = {
        "type": "object",
        "properties": {
            "screen": {"type": "string", "enum": screens},
            "text": {"type": "string"},
            "branch": enum(branches),
            "direction": enum(directions),
            "group": enum(groups),
            "child_status": enum(["active", "paused", "left"]),
            "has_debt": {"type": "boolean"},
            "debt_overdue": {"type": "boolean"},
            "expiring": {"type": "boolean"},
            "no_subscription": {"type": "boolean"},
            "lead_kind": {"type": "string", "enum": ["new", "renewal"]},
            "lead_source": enum(sources),
            "only_mine": {"type": "boolean"},
            "created_from": {"type": "string"},
            "created_to": {"type": "string"},
            "explanation": {"type": "string"},
        },
        "required": [
            "screen",
            "text",
            "branch",
            "direction",
            "group",
            "child_status",
            "has_debt",
            "debt_overdue",
            "expiring",
            "no_subscription",
            "lead_kind",
            "lead_source",
            "only_mine",
            "created_from",
            "created_to",
            "explanation",
        ],
        "additionalProperties": False,
    }
    lists = {
        "сегодня": timezone.localdate().isoformat(),
        "филиалы": list(branches),
        "направления": list(directions),
        "группы": list(groups),
        "источники заявок": list(sources),
    }
    data = _ask_json(
        system=SEARCH_SYSTEM,
        user=f"{json.dumps(lists, ensure_ascii=False)}\n\nЗапрос: {query}",
        schema=schema,
        max_tokens=1500,
    )

    def pick(mapping, key):
        item = mapping.get(data.get(key) or "")
        return str(item.id) if item else ""

    params = {"q": (data.get("text") or "").strip()}
    if data.get("screen") == "leads" and "leads" in screens:
        path = "/leads"
        created_from, created_to = (
            parse_date(data.get("created_from") or ""),
            parse_date(data.get("created_to") or ""),
        )
        params.update(
            {
                "branch": pick(branches, "branch"),
                "direction": pick(directions, "direction"),
                "source": pick(sources, "lead_source"),
                "kind": "renewal" if data.get("lead_kind") == "renewal" else "",
                "assigned_to": "me" if data.get("only_mine") else "",
                "created_from": created_from.isoformat() if created_from else "",
                "created_to": created_to.isoformat() if created_to else "",
                "view": "table",
            }
        )
    else:
        path = "/children"
        params.update(
            {
                "branch": pick(branches, "branch"),
                "direction": pick(directions, "direction"),
                "group": pick(groups, "group"),
                "status": data.get("child_status") or "",
            }
        )
        if can_view_client_money(user):
            for flag in ("has_debt", "debt_overdue", "expiring", "no_subscription"):
                params[flag] = "1" if data.get(flag) else ""
            if params["debt_overdue"]:
                params["has_debt"] = "1"
    query_string = urlencode({key: value for key, value in params.items() if value})
    return {
        "path": f"{path}?{query_string}" if query_string else path,
        "explanation": (data.get("explanation") or "").strip(),
    }


# --- Посещаемость по фото -------------------------------------------------

# Модель только переписывает таблицу с фото как есть. Какую колонку взять
# (по дате занятия), кто есть кто (фамилии → дети группы) и что значит значок —
# решает код ниже: так точнее и не зависит от того, насколько модель
# «догадливая» (проверено: переписать таблицу модели удаётся заметно лучше,
# чем сразу выставить отметки).
PHOTO_SYSTEM = """Перепиши таблицу посещаемости с фото бумажного журнала, доски или листа — ровно как написано, ничего не исправляя и не додумывая.
- dates — заголовки колонок с отметками слева направо, как написаны (например «14.10», «16.10», «пн»). Если колонка одна и без заголовка — [""].
- rows — строки с детьми сверху вниз: name — как написано в строке (фамилия, имя, сокращения); marks — значок в каждой колонке из dates, по порядку: «+», «н», «нб», «б», «✓», «-» или то, что написано. Пустая клетка — "" только если в ней действительно ничего нет: «+» бывает маленьким и смещённым к краю клетки — присмотрись к каждой клетке отдельно. Длина marks = длина dates.
- Строки, где нет имени ребёнка (заголовки, итоги), пропусти.
note — коротко по-русски, если фото нечитаемо местами, иначе пусто."""

PRESENT_MARKS = {"+", "б", "был", "была", "✓", "v", "1", "да", "п"}
ABSENT_MARKS = {"н", "нб", "н/б", "-", "–", "—", "0", "x", "х", "✗", "нет", "б/п", "бол", "болеет"}


def _norm(text: str) -> str:
    return " ".join(str(text or "").lower().replace("ё", "е").replace(".", " ").split())


def _mark_status(mark: str) -> str:
    mark = _norm(mark).replace(" ", "")
    if mark in PRESENT_MARKS:
        return "present"
    if mark in ABSENT_MARKS:
        return "absent"
    return "unknown"


def _date_column(dates: list[str], lesson_date) -> int | None:
    """Колонка за дату занятия: «16.10», «16/10», «16» — сравниваем день и
    месяц; одна колонка — она и есть; не нашли — None (всё «не разобрано»)."""
    import re

    if len(dates) == 1:
        return 0
    for index, header in enumerate(dates):
        numbers = [int(n) for n in re.findall(r"\d+", header or "")]
        if numbers[:2] == [lesson_date.day, lesson_date.month] or numbers == [lesson_date.day]:
            return index
    return None


def _match_children(participants, rows):
    """Строка журнала → ребёнок группы. Фамилия должна совпасть; однофамильцев
    различаем по имени или первой букве имени. Сомнительно — не сопоставляем."""

    def first_name_fits(first_name, tokens):
        # «Санжар» целиком или первая буква («С.» после _norm — «с»).
        return any(t == first_name or (len(t) == 1 and first_name.startswith(t)) for t in tokens)

    people = [(child, _norm(child.full_name).split()) for child in participants]
    matched = {}
    for row_index, row in enumerate(rows):
        tokens = _norm(row.get("name")).split()
        candidates = [(child, parts) for child, parts in people if parts and parts[0] in tokens]
        if len(candidates) > 1:  # однофамильцы — различаем по имени
            candidates = [
                (child, parts)
                for child, parts in candidates
                if len(parts) > 1
                and first_name_fits(parts[1], [t for t in tokens if t != parts[0]])
            ]
        if len(candidates) == 1 and candidates[0][0].id not in matched:
            matched[candidates[0][0].id] = row_index
    return matched


ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def attendance_from_photo(lesson, participants, uploaded) -> dict:
    """Предлагаемые отметки по фото: [{child, full_name, status}]. Ничего не
    сохраняет — преподаватель проверяет и сохраняет обычными отметками."""
    import base64

    if uploaded is None:
        raise AIError("Прикрепите фото журнала.")
    if uploaded.content_type not in ALLOWED_IMAGE_TYPES:
        raise AIError("Нужна фотография: JPG, PNG или WebP.")
    if uploaded.size > MAX_IMAGE_BYTES:
        raise AIError("Фото больше 8 МБ — сделайте снимок поменьше.")
    if not participants:
        raise AIError("На занятии нет детей.")
    image = (uploaded.content_type, base64.b64encode(uploaded.read()).decode())
    data = _ask_json(
        system=PHOTO_SYSTEM,
        user="Перепиши таблицу с фото.",
        schema={
            "type": "object",
            "properties": {
                "dates": {"type": "array", "items": {"type": "string"}},
                "rows": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "marks": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["name", "marks"],
                        "additionalProperties": False,
                    },
                },
                "note": {"type": "string"},
            },
            "required": ["dates", "rows", "note"],
            "additionalProperties": False,
        },
        max_tokens=4000,
        image=image,
    )
    rows = data.get("rows") or []
    lesson_date = timezone.localtime(lesson.starts_at).date()
    column = _date_column(data.get("dates") or [], lesson_date)
    notes = [(data.get("note") or "").strip()]
    if column is None:
        notes.append(f"На фото не нашлась колонка за {lesson_date:%d.%m} — отметьте вручную.")
    matched = _match_children(participants, rows) if column is not None else {}

    def status_for(child):
        row_index = matched.get(child.id)
        if row_index is None:
            return "unknown"
        marks = rows[row_index].get("marks") or []
        return _mark_status(marks[column]) if column < len(marks) else "unknown"

    return {
        "marks": [
            {"child": str(child.id), "full_name": child.full_name, "status": status_for(child)}
            for child in participants
        ],
        "note": " ".join(n for n in notes if n),
    }


# --- Импорт: «грязная» таблица → наш шаблон -------------------------------

IMPORT_SYSTEM = """Ты приводишь таблицу детского центра к шаблону импорта CRM. Таблицы у центров «грязные»: несколько телефонов в одной ячейке, роль родителя вместе с телефоном («мама 8707…»), имя и дата рождения в одной колонке, даты словами, пол по имени не указан, объединённые ячейки.
Для каждой строки исходной таблицы с ребёнком верни строку шаблона (row — номер исходной строки). Если в одной строке двое детей — верни две строки с тем же row. Строки без ребёнка (итоги, пустые, заголовки разделов) пропусти.
Поля:
- child_name — ФИО ребёнка как в таблице, без лишних пометок.
- birth_date — ДД.ММ.ГГГГ. Если только год или возраст — пусто (не выдумывай число и месяц).
- gender — «Ж» или «М». Если в таблице нет, определи по имени и фамилии, только если уверен; иначе пусто.
- parent_name — ФИО родителя (контактного лица).
- phone — телефон(ы) родителя; несколько — через запятую. Цифры как в таблице.
- role — мама, папа, бабушка, опекун или другое; пусто, если неизвестно.
- medical_notes — аллергии и особенности здоровья, если есть.
- reported_balance — остаток занятий числом, если есть колонка с остатком.
- direction, group — как в таблице, если есть.
- problem — коротко по-русски, что пришлось угадать (например «пол определён по имени», «остаток один на двоих детей»). Пусто, если ничего не угадывал.
Ничего не придумывай: чего нет в таблице — пустая строка."""

IMPORT_FIELDS = [
    "child_name",
    "birth_date",
    "gender",
    "parent_name",
    "phone",
    "role",
    "medical_notes",
    "reported_balance",
    "direction",
    "group",
]
IMPORT_MAX_ROWS = 300
IMPORT_CHUNK = 40


def _import_schema():
    row = {
        "type": "object",
        "properties": {
            "row": {"type": "integer"},
            **{field: {"type": "string"} for field in IMPORT_FIELDS},
            "gender": {"type": "string", "enum": ["Ж", "М", ""]},
            "role": {"type": "string", "enum": ["мама", "папа", "бабушка", "опекун", "другое", ""]},
            "problem": {"type": "string"},
        },
        "required": ["row", *IMPORT_FIELDS, "problem"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"rows": {"type": "array", "items": row}},
        "required": ["rows"],
        "additionalProperties": False,
    }


def _cell(value):
    if value is None:
        return ""
    return value.strftime("%d.%m.%Y") if hasattr(value, "strftime") else str(value).strip()


def _import_problems(row) -> str:
    """Что проверить в строке — обязательные поля шаблона проверяем сами, не
    полагаясь на то, что модель заметит; её пометку добавляем после."""
    problems = []
    if not (row.get("birth_date") or "").strip():
        problems.append("нет даты рождения")
    if not (row.get("gender") or "").strip():
        problems.append("не указан пол")
    if not (row.get("phone") or "").strip():
        problems.append("нет телефона")
    if not (row.get("parent_name") or "").strip():
        problems.append("нет ФИО родителя")
    note = (row.get("problem") or "").strip()
    if note and note.lower() not in "; ".join(problems):
        problems.append(note)
    return "; ".join(problems)


def clean_import_file(uploaded) -> dict:
    """Файл центра → строки шаблона импорта + .xlsx в формате шаблона.
    Дальше файл идёт обычным путём импорта (маппинг, сухой прогон, дубли) —
    запись в базу делает не ИИ."""
    import io
    from concurrent.futures import ThreadPoolExecutor

    import openpyxl
    from openpyxl.styles import Font

    from domains.people.clients import column_mapping

    if uploaded is None:
        raise AIError("Прикрепите файл.")
    try:
        headers, raw_rows, _meta = column_mapping.read_uploaded_file(uploaded, uploaded.name)
    except Exception as exc:  # noqa: BLE001 — битый файл — ошибка пользователя, не 500
        raise AIError("Не удалось прочитать файл — нужен .xlsx или .csv.") from exc
    if not raw_rows:
        raise AIError("В файле нет строк с данными.")
    if len(raw_rows) > IMPORT_MAX_ROWS:
        raise AIError(
            f"В пробной версии — до {IMPORT_MAX_ROWS} строк за раз. Разбейте файл на части."
        )

    def ask(chunk):
        table = [{"row": number, "cells": [_cell(v) for v in values]} for number, values in chunk]
        data = _ask_json(
            system=IMPORT_SYSTEM,
            user=f"Заголовки: {json.dumps(headers, ensure_ascii=False)}\nСтроки: {json.dumps(table, ensure_ascii=False)}",
            schema=_import_schema(),
            max_tokens=16000,
        )
        return data.get("rows") or []

    chunks = [raw_rows[i : i + IMPORT_CHUNK] for i in range(0, len(raw_rows), IMPORT_CHUNK)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(ask, chunks))
    rows = sorted((row for chunk in results for row in chunk), key=lambda r: r.get("row") or 0)
    for row in rows:
        row["problem"] = _import_problems(row)

    labels = {key: label for key, label, _ in column_mapping.SYSTEM_FIELDS}
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Дети"
    sheet.append(
        [labels[field] for field in IMPORT_FIELDS]
        + ["Строка исходного файла", "Что проверить (ИИ)"]
    )
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append(
            [row.get(field, "") for field in IMPORT_FIELDS]
            + [row.get("row"), row.get("problem", "")]
        )
    for index, width in enumerate([28, 14, 6, 28, 26, 10, 24, 10, 18, 18, 10, 40], start=1):
        sheet.column_dimensions[openpyxl.utils.get_column_letter(index)].width = width
    buffer = io.BytesIO()
    workbook.save(buffer)
    return {
        "rows": rows,
        "source_rows": len(raw_rows),
        "problems": sum(1 for row in rows if (row.get("problem") or "").strip()),
        "xlsx": buffer.getvalue(),
    }
