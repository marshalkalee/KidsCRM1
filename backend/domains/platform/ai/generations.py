"""Фоновая генерация по обезличенным агрегатам (TRU-159)."""

import copy
import json

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from domains.platform.tenants.models import Organization

from . import aggregates, generation_provider, services
from .models import AIGeneration
from .prompts import get_template


class AILimitExceeded(Exception):
    """Точка интеграции TRU-160: лимит проверяется до вызова провайдера."""


DEGRADATION_MESSAGES = {
    AIGeneration.Status.PROVIDER_UNAVAILABLE: (
        "ИИ временно недоступен — экран продолжает работать без рекомендаций."
    ),
    AIGeneration.Status.SCHEMA_ERROR: "Ответ не получился — попробуйте повторить позже.",
    AIGeneration.Status.LIMIT_EXHAUSTED: "Лимит ИИ на месяц исчерпан, обновится первого числа.",
    AIGeneration.Status.NO_KEY: "ИИ-помощник не настроен.",
    AIGeneration.Status.INPUT_TOO_LARGE: "Данных слишком много для одного запроса.",
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
    elif isinstance(value, int | float) and not isinstance(value, bool):
        result[prefix] = value
    return result


def enqueue(organization, template_key: str) -> AIGeneration:
    """Веб-слой только ставит задачу в очередь и сразу возвращает id."""
    template = get_template(template_key)
    generation = AIGeneration.objects.create(
        organization=organization,
        function=template.key,
        prompt_version=template.version,
        provider=services.provider(),
        model=generation_provider.model_name(),
    )
    from .tasks import run_ai_generation

    transaction.on_commit(lambda: run_ai_generation.delay(str(generation.id)))
    return generation


def _finish(generation_id, *, status, **fields):
    with transaction.atomic():
        generation = AIGeneration.objects.select_for_update().get(pk=generation_id)
        generation.status = status
        generation.finished_at = timezone.now()
        for name, value in fields.items():
            setattr(generation, name, value)
        generation.save(update_fields=["status", "finished_at", "updated_at", *fields.keys()])
    return generation


def _fixture_payload(template, facts, snapshot):
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
    return payload


def run(generation_id) -> AIGeneration:
    generation = AIGeneration.objects.select_related("organization").get(pk=generation_id)
    template = get_template(generation.function)
    AIGeneration.objects.filter(pk=generation.id).update(status=AIGeneration.Status.RUNNING)

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
    except AILimitExceeded:
        return _finish(
            generation.id,
            status=AIGeneration.Status.LIMIT_EXHAUSTED,
            error_code="limit_exhausted",
            error_detail=DEGRADATION_MESSAGES[AIGeneration.Status.LIMIT_EXHAUSTED],
        )

    snapshot = aggregates.snapshot(generation.organization)
    facts = numeric_facts(snapshot)
    user = json.dumps({"aggregates": snapshot, "facts": facts}, ensure_ascii=False, sort_keys=True)
    request_chars = len(template.system) + len(user)
    if request_chars > settings.AI_GENERATION_MAX_INPUT_CHARS:
        return _finish(
            generation.id,
            status=AIGeneration.Status.INPUT_TOO_LARGE,
            request_chars=request_chars,
            error_code="input_too_large",
            error_detail=DEGRADATION_MESSAGES[AIGeneration.Status.INPUT_TOO_LARGE],
        )

    input_tokens = output_tokens = 0
    last_error = None
    for attempt in range(1, 3):
        try:
            if fixture_mode:
                payload = _fixture_payload(template, facts, snapshot)
            else:
                response = generation_provider.call(
                    system=template.system,
                    user=user,
                    schema=template.schema,
                    model=generation.model,
                    max_tokens=template.max_tokens,
                )
                payload = response.payload
                input_tokens += response.input_tokens
                output_tokens += response.output_tokens
            result = template.validate(payload, facts, snapshot)
        except ValueError as exc:
            last_error = exc
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
        error_detail=str(last_error)[:500],
    )


def ensure_within_limit(organization: Organization) -> None:
    """TRU-160 заменит тело проверкой месячного лимита организации."""
