"""Единый низкоуровневый вызов structured output с учётом токенов."""

import json
from dataclasses import dataclass

import anthropic
from django.conf import settings

from . import services


@dataclass(frozen=True)
class ProviderResult:
    payload: dict
    input_tokens: int
    output_tokens: int


def _json(text: str) -> dict:
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("provider returned non-JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("provider returned non-object JSON")
    return value


def call(*, system: str, user: str, schema: dict, model: str, max_tokens: int) -> ProviderResult:
    if services.provider() == "openai":
        return _openai(system=system, user=user, schema=schema, model=model, max_tokens=max_tokens)
    return _anthropic(system=system, user=user, schema=schema, model=model, max_tokens=max_tokens)


def _openai(*, system, user, schema, model, max_tokens):
    import openai

    try:
        response = services._openai_client().chat.completions.create(
            model=model,
            max_completion_tokens=max_tokens,
            temperature=0,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": schema, "strict": True},
            },
        )
    except openai.RateLimitError as exc:
        raise services.AIError("ИИ сейчас перегружен — попробуйте позже.") from exc
    except (openai.APIConnectionError, openai.APIStatusError) as exc:
        raise services.AIError("ИИ временно недоступен.") from exc
    except openai.AuthenticationError as exc:
        raise services.AIError("Ключ ИИ не подошёл.") from exc
    choice = response.choices[0]
    if choice.message.refusal or choice.finish_reason == "length":
        raise services.AIError("Ответ ИИ не получился.")
    usage = getattr(response, "usage", None)
    return ProviderResult(
        _json(choice.message.content or ""),
        int(getattr(usage, "prompt_tokens", 0) or 0),
        int(getattr(usage, "completion_tokens", 0) or 0),
    )


def _anthropic(*, system, user, schema, model, max_tokens):
    try:
        response = services._client().beta.messages.create(
            model=model,
            max_tokens=max_tokens,
            betas=[services.FALLBACK_BETA],
            fallbacks="default",
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        )
    except anthropic.RateLimitError as exc:
        raise services.AIError("ИИ сейчас перегружен — попробуйте позже.") from exc
    except (anthropic.APIConnectionError, anthropic.APIStatusError) as exc:
        raise services.AIError("ИИ временно недоступен.") from exc
    if response.stop_reason in {"refusal", "max_tokens"}:
        raise services.AIError("Ответ ИИ не получился.")
    text = next((block.text for block in response.content if block.type == "text"), "")
    usage = getattr(response, "usage", None)
    return ProviderResult(
        _json(text),
        int(getattr(usage, "input_tokens", 0) or 0),
        int(getattr(usage, "output_tokens", 0) or 0),
    )


def model_name() -> str:
    return settings.OPENAI_DIGEST_MODEL if services.provider() == "openai" else settings.AI_MODEL
