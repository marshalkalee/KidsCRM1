"""Фоновая генерация по обезличенным агрегатам (TRU-159)."""

import copy
import json
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from domains.platform.tenants.models import Organization

from . import aggregates, generation_provider, services, usage
from .models import AIGeneration
from .prompts import get_template

# Лимит месяца — общий для всех функций помощника (usage.py, TRU-160).
AILimitExceeded = usage.AILimitExceeded


DEGRADATION_MESSAGES = {
    AIGeneration.Status.PROVIDER_UNAVAILABLE: (
        "ИИ временно недоступен — экран продолжает работать без рекомендаций."
    ),
    AIGeneration.Status.SCHEMA_ERROR: "Ответ не получился — попробуйте повторить позже.",
    AIGeneration.Status.LIMIT_EXHAUSTED: "Лимит ИИ на месяц исчерпан, обновится первого числа.",
    AIGeneration.Status.NO_KEY: "ИИ-помощник не настроен.",
    AIGeneration.Status.INPUT_TOO_LARGE: "Данных слишком много для одного запроса.",
}

LANGUAGE_INSTRUCTIONS = {
    "ru": "Пиши все человекочитаемые поля ответа на русском языке.",
    "kk": "Барлық адам оқитын жауап өрістерін қазақ тілінде жаз.",
    "en": "Write all human-readable response fields in English.",
}


def numeric_facts(value, prefix="") -> dict:
    """Плоская карта чисел: только она может попасть в итоговую выдачу."""
    result = {}
    if isinstance(value, dict):
        for key, item in value.items():
            result.update(numeric_facts(item, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            result.update(numeric_facts(item, f"{prefix}[{index}]"))
    elif isinstance(value, Decimal):
        # Деньги в агрегатах — Decimal: тоже факт, в JSON — числом.
        result[prefix] = int(value) if value == value.to_integral_value() else float(value)
    elif isinstance(value, int | float) and not isinstance(value, bool):
        result[prefix] = value
    return result


def create(organization, template_key: str, parameters=None) -> AIGeneration:
    """Запись журнала в очереди, без запуска: enqueue ставит её в Celery,
    дайджест (digest.py) прогоняет блоки сам — он уже фоновая задача."""
    template = get_template(template_key)
    return AIGeneration.objects.create(
        organization=organization,
        function=template.key,
        prompt_version=template.version,
        provider=services.provider(),
        model=generation_provider.model_name(),
        parameters=parameters or {},
    )


def enqueue(organization, template_key: str, parameters=None) -> AIGeneration:
    """Веб-слой только ставит задачу в очередь и сразу возвращает id.

    Лимит проверяется здесь, до очереди (TRU-160): исчерпан — запись сразу
    получает своё состояние, задача не ставится. Начатая генерация
    доводится до конца, даже если вышла за лимит."""
    generation = create(organization, template_key, parameters=parameters)
    try:
        ensure_within_limit(organization)
    except AILimitExceeded as exc:
        return _finish(
            generation.id,
            status=AIGeneration.Status.LIMIT_EXHAUSTED,
            error_code="limit_exhausted",
            error_detail=str(exc),
        )
    from .tasks import run_ai_generation

    transaction.on_commit(lambda: run_ai_generation.delay(str(generation.id)))
    return generation


def _finish(generation_id, *, status, **fields):
    with transaction.atomic():
        generation = AIGeneration.objects.select_for_update().get(pk=generation_id)
        if generation.status == AIGeneration.Status.CANCELLED:
            return generation
        generation.status = status
        generation.finished_at = timezone.now()
        for name, value in fields.items():
            setattr(generation, name, value)
        generation.save(update_fields=["status", "finished_at", "updated_at", *fields.keys()])
    return generation


def _fixture_payload(template, facts, snapshot, parameters=None):
    payload = copy.deepcopy(template.fixture)
    first_key = next(iter(facts), None)
    if first_key:
        for row in payload.get("recommendations", []):
            row["evidence_keys"] = [first_key]
    candidates = [
        item["candidate_key"]
        for item in snapshot.get("promotion_opportunities", {}).get("кандидаты", [])
    ]
    if candidates:
        for row in payload.get("recommendations", []):
            row["candidate_key"] = candidates[0]
        for section in ("campaigns", "plan", "posts", "videos"):
            for row in payload.get(section, []):
                row["candidate_key"] = candidates[0]
        if template.key == "content_studio":
            parameters = parameters or {}
            content_type = parameters.get("content_type", "both")
            if content_type in {"full", "week"}:
                content_type = "both"
            count = int(parameters.get("content_count", 3))
            for section in ("campaigns", "plan"):
                payload[section] = []
            for section, enabled in (
                ("posts", content_type in {"post", "both"}),
                ("videos", content_type in {"reel", "both"}),
            ):
                seed = payload[section][0] if payload[section] and enabled else None
                payload[section] = [copy.deepcopy(seed) for _ in range(count)] if seed else []
    elif template.key in {"group_promotion", "content_studio"}:
        for section in ("recommendations", "campaigns", "plan", "posts", "videos"):
            if section in payload:
                payload[section] = []
    return payload


def _snapshot_for_provider(snapshot, function):
    """Keep CRM labels that must be rendered by code out of the model request."""
    prepared = copy.deepcopy(snapshot)
    if function == "content_studio":
        candidates = prepared.get("promotion_opportunities", {}).get("кандидаты", [])
        for candidate in candidates:
            candidate.pop("группа", None)
            candidate.pop("филиал", None)
            candidate.pop("расписание", None)
    return prepared


def run(generation_id) -> AIGeneration:
    with transaction.atomic():
        generation = (
            AIGeneration.objects.select_for_update()
            .select_related("organization")
            .get(pk=generation_id)
        )
        if generation.status == AIGeneration.Status.CANCELLED:
            return generation
        generation.status = AIGeneration.Status.RUNNING
        generation.save(update_fields=["status", "updated_at"])
    template = get_template(generation.function)

    fixture_mode = settings.AI_FIXTURE_MODE and not services.is_enabled()
    if not services.is_enabled() and not fixture_mode:
        return _finish(
            generation.id,
            status=AIGeneration.Status.NO_KEY,
            error_code="no_key",
            error_detail=DEGRADATION_MESSAGES[AIGeneration.Status.NO_KEY],
        )

    try:
        ensure_within_limit(generation.organization)
    except AILimitExceeded as exc:
        return _finish(
            generation.id,
            status=AIGeneration.Status.LIMIT_EXHAUSTED,
            error_code="limit_exhausted",
            error_detail=str(exc),
        )

    snapshot = aggregates.snapshot(generation.organization)
    facts = numeric_facts(snapshot)
    provider_snapshot = _snapshot_for_provider(snapshot, generation.function)
    user = json.dumps(
        {
            "aggregates": provider_snapshot,
            "facts": facts,
            "parameters": generation.parameters,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    language_instruction = LANGUAGE_INSTRUCTIONS.get(generation.parameters.get("language"), "")
    request_context = f"{user}\n\n{language_instruction}" if language_instruction else user
    request_chars = len(template.system) + len(request_context)
    if request_chars > settings.AI_GENERATION_MAX_INPUT_CHARS:
        return _finish(
            generation.id,
            status=AIGeneration.Status.INPUT_TOO_LARGE,
            request_chars=request_chars,
            error_code="input_too_large",
            error_detail=DEGRADATION_MESSAGES[AIGeneration.Status.INPUT_TOO_LARGE],
        )

    input_tokens = output_tokens = 0
    provider_user = request_context
    for attempt in range(1, 3):
        try:
            if fixture_mode:
                payload = _fixture_payload(template, facts, snapshot, generation.parameters)
            else:
                response = generation_provider.call(
                    system=template.system,
                    user=provider_user,
                    schema=template.schema,
                    model=generation.model,
                    max_tokens=template.max_tokens,
                )
                # Учёт — сразу после ответа, отдельной строкой на каждую попытку:
                # невалидный ответ тоже оплачен.
                usage.record(
                    generation.organization,
                    feature=generation.function,
                    model=generation.model,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    generation=generation,
                )
                payload = response.payload
                input_tokens += response.input_tokens
                output_tokens += response.output_tokens
            result = template.validate(payload, facts, snapshot, generation.parameters)
        except ValueError:
            provider_user = (
                f"{request_context}\n\n"
                "Предыдущий ответ не прошёл проверку. Создай новый JSON с нуля. "
                "Не используй цифры, проценты, цены, размеры скидок, сроки акции "
                "или другие неподтверждённые условия в текстовых полях. "
                "Не повторяй названия группы и филиала — приложение подставит их само."
            )
            continue
        except services.AIError as exc:
            return _finish(
                generation.id,
                status=AIGeneration.Status.PROVIDER_UNAVAILABLE,
                attempts=attempt,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                request_chars=request_chars,
                error_code="provider_unavailable",
                error_detail=str(exc)[:500],
            )
        if template.finalize:
            result = template.finalize(generation.organization, result, snapshot)
        return _finish(
            generation.id,
            status=AIGeneration.Status.SUCCEEDED,
            attempts=attempt,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            request_chars=request_chars,
            result=result,
            error_code="",
            error_detail="",
        )
    return _finish(
        generation.id,
        status=AIGeneration.Status.SCHEMA_ERROR,
        attempts=2,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        request_chars=request_chars,
        error_code="schema_error",
        error_detail=DEGRADATION_MESSAGES[AIGeneration.Status.SCHEMA_ERROR],
    )


def ensure_within_limit(organization: Organization) -> None:
    usage.ensure_within_limit(organization)
