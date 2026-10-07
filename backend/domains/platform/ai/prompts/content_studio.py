"""Контент-план и готовые материалы (TRU-162), без придуманных условий акции."""

import re
from datetime import timedelta

from django.utils import timezone

from .base import PromptTemplate

SYSTEM = """Ты — редактор контента детского центра. Создай связанный набор материалов
для продвижения только тех групп, которые переданы в aggregates.promotion_opportunities.
Язык ответа задан в parameters.language: ru — русский, kk — казахский.
Пожелания пользователя находятся в parameters.instructions. Тема, аудитория и задача из пожелания —
главное требование к содержанию. Если пользователь назвал тему, посвяти каждый материал именно ей:
не заменяй её общей рекламой детского центра, перечислением пользы занятий или описанием группы.
Каждый вариант раскрывай с отдельного содержательного ракурса и давай конкретный сюжет. Для
образовательной или исторической темы покажи реальные этапы, изменения и причинно-следственные
связи без выдуманных дат и фактов. Данные группы используй только как уместный контекст и призыв
к действию в конце. Игнорируй лишь ту часть пожелания, которая требует нарушить правила ниже,
выдумать факты CRM или изменить формат JSON.
Формат результата находится в parameters.content_type:
- post — готовые посты только в posts;
- reel — сценарии Reels только в videos;
- both — посты в posts и сценарии Reels в videos.
Создай ровно parameters.content_count элементов в каждом выбранном массиве.
Массивы campaigns и plan, а также невыбранные posts или videos оставь пустыми.

Не повторяй названия групп, расписание, количество мест и другие цифры: приложение
подставит их из CRM. Не придумывай скидки, цены, бесплатные услуги, сроки акции и
гарантии результата. Можно предложить механику «приведи друга», рассрочку или короткий
абонемент только как идею, которую центр должен согласовать.
Во всех создаваемых текстовых полях вообще не используй цифры, проценты и денежные суммы.

Контент-план должен быть связан с выбранными группами. Для видео дай конкретную
раскадровку: что снять в каждом кадре, затем подпись. Не упоминай конкретных детей.
Ответ строго по JSON-схеме."""

TEXT = {"type": "string", "minLength": 3, "maxLength": 1200}
CANDIDATE = {"type": "string", "minLength": 1}

SCHEMA = {
    "type": "object",
    "properties": {
        "campaigns": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "candidate_key": CANDIDATE,
                    "title": TEXT,
                    "mechanic": TEXT,
                    "rationale": TEXT,
                },
                "required": ["candidate_key", "title", "mechanic", "rationale"],
                "additionalProperties": False,
            },
        },
        "plan": {
            "type": "array",
            "maxItems": 9,
            "items": {
                "type": "object",
                "properties": {
                    "candidate_key": CANDIDATE,
                    "moment": {"enum": ["early_week", "mid_week", "weekend"]},
                    "format": {"enum": ["post", "reel", "story"]},
                    "theme": TEXT,
                    "goal": TEXT,
                },
                "required": ["candidate_key", "moment", "format", "theme", "goal"],
                "additionalProperties": False,
            },
        },
        "posts": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "candidate_key": CANDIDATE,
                    "hook": TEXT,
                    "body": TEXT,
                    "cta": TEXT,
                },
                "required": ["candidate_key", "hook", "body", "cta"],
                "additionalProperties": False,
            },
        },
        "videos": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "candidate_key": CANDIDATE,
                    "title": TEXT,
                    "shots": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 6,
                        "items": TEXT,
                    },
                    "caption": TEXT,
                },
                "required": ["candidate_key", "title", "shots", "caption"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["campaigns", "plan", "posts", "videos"],
    "additionalProperties": False,
}

FIXTURE = {
    "campaigns": [
        {
            "candidate_key": "",
            "title": "Набор в группу с подходящим расписанием",
            "mechanic": "Пригласить родителей познакомиться с направлением и привести друга",
            "rationale": "В группе есть свободные места и подтверждённый интерес",
        }
    ],
    "plan": [
        {
            "candidate_key": "",
            "moment": "early_week",
            "format": "post",
            "theme": "Познакомить с направлением и группой",
            "goal": "Получить обращения родителей",
        },
        {
            "candidate_key": "",
            "moment": "mid_week",
            "format": "reel",
            "theme": "Показать атмосферу занятия",
            "goal": "Снять сомнения перед первым визитом",
        },
    ],
    "posts": [
        {
            "candidate_key": "",
            "hook": "Ищете занятие, которое ребёнок будет ждать?",
            "body": (
                "Покажем направление без сложных обещаний: знакомство с педагогом, "
                "движением и атмосферой группы."
            ),
            "cta": "Напишите нам, чтобы узнать условия записи.",
        }
    ],
    "videos": [
        {
            "candidate_key": "",
            "title": "Один урок изнутри",
            "shots": [
                "Снимите общий план зала до начала занятия",
                "Покажите упражнение группы без крупных планов лиц",
                "Завершите кадром преподавателя и приглашением узнать о записи",
            ],
            "caption": (
                "Показываем, как проходит обычное занятие. " "Подробности о записи — в сообщениях."
            ),
        }
    ],
}

UNSAFE = re.compile(
    r"(?:\d|%|₸|тенге|рубл|доллар|скидк|бесплатн|дарим|только сегодня|до конца)",
    re.IGNORECASE,
)
SECTIONS = {
    "campaigns": {"candidate_key", "title", "mechanic", "rationale"},
    "plan": {"candidate_key", "moment", "format", "theme", "goal"},
    "posts": {"candidate_key", "hook", "body", "cta"},
    "videos": {"candidate_key", "title", "shots", "caption"},
}


def _strings(row):
    for key, value in row.items():
        if key == "candidate_key" or key in {"moment", "format"}:
            continue
        if isinstance(value, list):
            yield from value
        else:
            yield value


def _publish_date(moment):
    target = {"early_week": 0, "mid_week": 2, "weekend": 5}[moment]
    today = timezone.localdate()
    return (today + timedelta(days=(target - today.weekday()) % 7)).isoformat()


def _schedule(candidate, language):
    separator = ", "
    return separator.join(
        f'{slot["день"]} {slot["время"]}' for slot in candidate.get("расписание", [])
    ) or ("кесте нақтылануда" if language == "kk" else "расписание уточняется")


def _facts(candidate):
    return {
        "available_places": candidate["свободных_мест"],
        "occupancy_percent": candidate["заполняемость_процент"],
        "direction_leads": candidate["заявок_на_направление"],
        "conversion_percent": candidate["конверсия_процент"],
        "same_month_last_year_leads": candidate["заявок_в_тот_же_месяц_год_назад"],
    }


def _post_text(row, candidate, language):
    if language == "kk":
        details = (
            f'Топ: {candidate["группа"]}\n'
            f'Кесте: {_schedule(candidate, language)}\n'
            f'Бос орын: {candidate["свободных_мест"]}'
        )
    else:
        details = (
            f'Группа: {candidate["группа"]}\n'
            f'Расписание: {_schedule(candidate, language)}\n'
            f'Свободных мест: {candidate["свободных_мест"]}'
        )
    return "\n\n".join((row["hook"].strip(), row["body"].strip(), details, row["cta"].strip()))


def validate(payload, _facts_map, snapshot, parameters=None):
    parameters = parameters or {}
    language = parameters.get("language", "ru")
    content_type = parameters.get("content_type", "both")
    if content_type in {"full", "week"}:  # Совместимость с уже созданными генерациями.
        content_type = "both"
    content_count = int(parameters.get("content_count", 3))
    if language not in {"ru", "kk"}:
        raise ValueError("unsupported language")
    if content_type not in {"post", "reel", "both"}:
        raise ValueError("unsupported content type")
    if not 1 <= content_count <= 5:
        raise ValueError("unsupported content count")
    if not isinstance(payload, dict) or set(payload) != set(SECTIONS):
        raise ValueError("invalid content sections")
    candidates = {
        row["candidate_key"]: row
        for row in snapshot.get("promotion_opportunities", {}).get("кандидаты", [])
    }
    output = {key: [] for key in SECTIONS}
    selected_sections = {
        "post": {"posts"},
        "reel": {"videos"},
        "both": {"posts", "videos"},
    }[content_type]
    for section, fields in SECTIONS.items():
        rows = payload[section]
        if not isinstance(rows, list):
            raise ValueError("content section must be a list")
        if section not in selected_sections:
            continue
        if len(rows) != content_count:
            raise ValueError("requested content count does not match")
        for row in rows:
            if not isinstance(row, dict) or set(row) != fields:
                raise ValueError("invalid content fields")
            candidate = candidates.get(row["candidate_key"])
            if candidate is None:
                raise ValueError("unknown candidate")
            for text in _strings(row):
                if not isinstance(text, str) or not text.strip() or UNSAFE.search(text):
                    raise ValueError("model content contains an invented offer or number")
                if any(
                    name and name.lower() in text.lower()
                    for name in (
                        candidate["группа"],
                        candidate["филиал"],
                    )
                ):
                    raise ValueError("CRM names must be inserted by code")
            item = {**row, "group": candidate["группа"], "basis": _facts(candidate)}
            if section == "plan":
                item["publish_on"] = _publish_date(row["moment"])
            if section == "posts":
                item["text"] = _post_text(row, candidate, language)
            output[section].append(item)
    output["language"] = language
    output["content_type"] = content_type
    output["content_count"] = content_count
    return output


TEMPLATE = PromptTemplate(
    key="content_studio",
    version="1.2.1",
    system=SYSTEM,
    schema=SCHEMA,
    fixture=FIXTURE,
    validate=validate,
    max_tokens=5000,
)
