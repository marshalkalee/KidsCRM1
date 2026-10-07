"""Какие группы продвигать (TRU-161). Цифры в результат подставляет код."""

import re

from ..recommendations import remember
from .base import PromptTemplate

SYSTEM = """Ты помогаешь владельцу детского центра выбрать группы для продвижения.
Кандидаты уже отсортированы кодом: сначала быстрая победа, затем создание спроса.
Учитывай сезон, прошлый год и системную проблему направления в филиале.
Выбери до пяти candidate_key. Не придумывай группы и не пиши цифры словами или знаками:
конкретные значения приложение подставит само. Объясни решение коротко и по делу.
Ответ строго по JSON-схеме."""

SCHEMA = {
    "type": "object",
    "properties": {
        "recommendations": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "candidate_key": {"type": "string"},
                    "title": {"type": "string"},
                    "rationale": {"type": "string"},
                    "action": {"type": "string"},
                },
                "required": ["candidate_key", "title", "rationale", "action"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["recommendations"],
    "additionalProperties": False,
}

FIXTURE = {
    "recommendations": [
        {
            "candidate_key": "",
            "title": "Продвигайте группу с потенциалом набора",
            "rationale": "Свободные места и история спроса дают основание для действия",
            "action": "Запустите предложение через подходящий источник",
        }
    ]
}


def validate(payload, _facts, snapshot):
    if not isinstance(payload, dict) or set(payload) != {"recommendations"}:
        raise ValueError("recommendations is required")
    rows = payload["recommendations"]
    if not isinstance(rows, list) or len(rows) > 5:
        raise ValueError("recommendations must be a list with up to five items")
    candidates = {
        item["candidate_key"]: item
        for item in snapshot.get("promotion_opportunities", {}).get("кандидаты", [])
    }
    output = []
    required = {"candidate_key", "title", "rationale", "action"}
    for row in rows:
        if not isinstance(row, dict) or set(row) != required:
            raise ValueError("invalid recommendation fields")
        candidate = candidates.get(row["candidate_key"])
        if candidate is None:
            raise ValueError("unknown candidate")
        for name in ("title", "rationale", "action"):
            invalid_text = (
                not isinstance(row[name], str)
                or not row[name].strip()
                or re.search(r"\d", row[name])
            )
            if invalid_text:
                raise ValueError("model text must be non-empty and contain no numbers")
        output.append(
            {
                "candidate_key": candidate["candidate_key"],
                "group": candidate["группа"],
                "branch": candidate["филиал"],
                "direction": candidate["направление"],
                "case": candidate["случай"],
                "systemic": candidate["системная_проблема_направления_в_филиале"],
                "season": candidate["сезон"],
                "title": row["title"].strip(),
                "rationale": row["rationale"].strip(),
                "action": row["action"].strip(),
                "basis": {
                    "available_places": candidate["свободных_мест"],
                    "occupancy_percent": candidate["заполняемость_процент"],
                    "direction_leads": candidate["заявок_на_направление"],
                    "purchased": candidate["купили"],
                    "conversion_percent": candidate["конверсия_процент"],
                    "same_month_last_year_leads": candidate["заявок_в_тот_же_месяц_год_назад"],
                    "age_sources": candidate["источники_этого_возраста"],
                },
            }
        )
    return {"recommendations": output}


TEMPLATE = PromptTemplate(
    key="group_promotion",
    version="1.0.0",
    system=SYSTEM,
    schema=SCHEMA,
    fixture=FIXTURE,
    validate=validate,
    finalize=remember,
)
