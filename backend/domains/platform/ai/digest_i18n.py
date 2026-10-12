"""
Дайджест на трёх языках (ru, kk, en) одной сборкой.

Советы модель пишет один раз — по-русски; затем один короткий запрос
переводит готовые тексты (заголовки, советы, подписи цифр, «что
изменилось») на казахский и английский. Перевод хранится в самом
дайджесте (`content["i18n"]`: язык → {русский текст: перевод}), поэтому
смена языка на экране ничего не генерирует заново и ничего не стоит.

Не удался перевод — дайджест всё равно готов: на другом языке
показывается русский текст, а не ошибка.
"""

import copy
import json
import logging

from django.conf import settings

from . import generation_provider, services, usage

logger = logging.getLogger(__name__)

SOURCE = "ru"
TARGETS = ("kk", "en")
LANGUAGES = (SOURCE, *TARGETS)
FEATURE = "digest_translation"

SYSTEM = """Ты переводишь короткие тексты еженедельного дайджеста детского центра
с русского на казахский (kk) и английский (en). Переводи по смыслу, простым
деловым языком, как пишут владельцу центра. Не меняй имена людей, названия
групп, направлений, филиалов и центров, числа, даты, проценты, диапазоны и знаки.
Сохраняй пунктуацию оригинала: нет точки в конце — не добавляй.
Верни для каждого языка столько же строк, сколько получил, в том же порядке.
Ответ строго по JSON-схеме."""

SCHEMA = {
    "type": "object",
    "properties": {lang: {"type": "array", "items": {"type": "string"}} for lang in TARGETS},
    "required": list(TARGETS),
    "additionalProperties": False,
}


def _item_texts(item):
    yield item.get("title")
    yield item.get("rationale")
    yield item.get("action")
    for evidence in item.get("evidence", []):
        yield evidence.get("label")


def texts_of(content: dict) -> list[str]:
    """Все человекочитаемые строки дайджеста — по одному разу, по порядку."""
    seen, texts = set(), []

    def add(value):
        if isinstance(value, str) and value.strip() and value not in seen:
            seen.add(value)
            texts.append(value)

    for item in content.get("items", []):
        for value in _item_texts(item):
            add(value)
    for block in content.get("blocks", []):
        add(block.get("title"))
    changes = content.get("changes") or {}
    for title in (*changes.get("new", []), *changes.get("gone", [])):
        add(title)
    for value in changes.get("values", []):
        add(value.get("label"))
    return texts


def _short_model() -> str:
    return settings.OPENAI_MODEL if services.provider() == "openai" else settings.AI_MODEL


def translate(organization, content: dict) -> dict:
    """{язык: {русский текст: перевод}} для kk и en; {} — если перевести не вышло."""
    texts = texts_of(content)
    if not texts:
        return {}
    if not services.is_enabled():
        # Тесты и стенд без ключа: «перевод» — тот же текст, экран не ломается.
        return (
            {lang: {text: text for text in texts} for lang in TARGETS}
            if (settings.AI_FIXTURE_MODE)
            else {}
        )
    model = _short_model()
    try:
        response = generation_provider.call(
            system=SYSTEM,
            user=json.dumps({"texts": texts}, ensure_ascii=False),
            schema=SCHEMA,
            model=model,
            max_tokens=min(8000, 600 + 60 * len(texts)),
        )
    except services.AIError:
        logger.warning("Digest translation failed for %s", organization.pk, exc_info=True)
        return {}
    usage.record(
        organization,
        feature=FEATURE,
        model=model,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )
    payload = response.payload if isinstance(response.payload, dict) else {}
    result = {}
    for lang in TARGETS:
        rows = payload.get(lang)
        if (
            isinstance(rows, list)
            and len(rows) == len(texts)
            and all(isinstance(row, str) and row.strip() for row in rows)
        ):
            result[lang] = {text: row.strip() for text, row in zip(texts, rows, strict=True)}
    return result


def localize(content: dict, language: str) -> dict:
    """Копия содержимого дайджеста на нужном языке; служебный `i18n` не отдаём."""
    content = copy.deepcopy(content or {})
    table = (content.pop("i18n", None) or {}).get(language) or {}
    if not table:
        return content

    def tr(value):
        return table.get(value, value) if isinstance(value, str) else value

    def item(row):
        for name in ("title", "rationale", "action"):
            if name in row:
                row[name] = tr(row[name])
        for evidence in row.get("evidence", []):
            if "label" in evidence:
                evidence["label"] = tr(evidence["label"])

    for name in ("items", "highlights"):
        for row in content.get(name, []):
            item(row)
    for block in content.get("blocks", []):
        block["title"] = tr(block.get("title"))
        for row in block.get("items", []):
            item(row)
    changes = content.get("changes") or {}
    for name in ("new", "gone"):
        if name in changes:
            changes[name] = [tr(title) for title in changes[name]]
    for value in changes.get("values", []):
        value["label"] = tr(value.get("label"))
    return content
