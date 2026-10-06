"""Базовый шаблон рекомендаций; TRU-161/162 расширяют реестр своими шаблонами."""

import re

from .base import PromptTemplate

SYSTEM = """Ты маркетинговый помощник детского центра.
Ранжируй рекомендации только по переданным обезличенным фактам.
Не пиши цифры в title, rationale и action: все числа приложение добавит само.
Для доказательств возвращай только ключи из списка facts. Не выдумывай факты.
Ответ должен строго соответствовать JSON-схеме."""

SCHEMA = {
    "type": "object",
    "properties": {
        "recommendations": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "rationale": {"type": "string"},
                    "action": {"type": "string"},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    "evidence_keys": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 4,
                        "items": {"type": "string"},
                    },
                },
                "required": ["title", "rationale", "action", "priority", "evidence_keys"],
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
            "title": "Проверьте группы с недобором",
            "rationale": "Заполняемость показывает потенциал для продвижения",
            "action": "Подготовьте предложение для подходящей аудитории",
            "priority": "high",
            "evidence_keys": [],
        }
    ]
}


def validate(payload: dict, facts: dict, _snapshot: dict) -> dict:
    if not isinstance(payload, dict) or set(payload) != {"recommendations"}:
        raise ValueError("recommendations is required")
    rows = payload["recommendations"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 5:
        raise ValueError("recommendations must contain 1..5 items")
    result = []
    required = {"title", "rationale", "action", "priority", "evidence_keys"}
    for row in rows:
        if not isinstance(row, dict) or set(row) != required:
            raise ValueError("invalid recommendation fields")
        if row["priority"] not in {"high", "medium", "low"}:
            raise ValueError("invalid priority")
        for name in ("title", "rationale", "action"):
            if not isinstance(row[name], str) or not row[name].strip():
                raise ValueError(f"{name} must be a non-empty string")
            if re.search(r"\d", row[name]):
                raise ValueError("model-authored text must not contain numbers")
        keys = row["evidence_keys"]
        if not isinstance(keys, list) or not 1 <= len(keys) <= 4:
            raise ValueError("evidence_keys must contain 1..4 items")
        if any(not isinstance(key, str) or key not in facts for key in keys):
            raise ValueError("unknown evidence key")
        result.append(
            {
                **{name: row[name].strip() for name in ("title", "rationale", "action")},
                "priority": row["priority"],
                # Числа берутся только из snapshot, не из ответа модели.
                "evidence": [{"key": key, "value": facts[key]} for key in keys],
            }
        )
    return {"recommendations": result}


TEMPLATE = PromptTemplate(
    key="marketing_recommendations",
    version="1.0.0",
    system=SYSTEM,
    schema=SCHEMA,
    fixture=FIXTURE,
    validate=validate,
)
