"""
Учёт расхода ИИ и лимит центра (TRU-160, ADR-0009 раздел 5).

Каждое обращение к модели — строка AIUsage: функция, модель, токены,
стоимость в $. Месячный расход, лимит и экран владельца считаются по этим
строкам, поэтому расход не может разойтись с журналом.

Лимит проверяется перед началом работы (вопрос в чате, короткая задача,
постановка генерации). Начатое доводится до конца, даже если вышло за
лимит на несколько процентов: обрывать дайджест на середине хуже.
"""

import logging
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Count, Sum
from django.utils import timezone

from .models import AIUsage
from .services import AIError

logger = logging.getLogger(__name__)

# Функция → подпись на экране расхода. Короткие задачи владельцу не важны
# по отдельности — показываем одной строкой.
SHORT_TASKS = "short_tasks"
FEATURE_GROUPS = {
    "chat": "chat",
    "marketing_recommendations": "digest",
    "group_promotion": "digest",
    "digest_translation": "digest",
    "attendance_photo": "attendance_photo",
    "import_clean": "import_clean",
}
GROUP_LABELS = {
    "chat": "Чат с помощником",
    "digest": "Рекомендации и дайджест",
    "attendance_photo": "Посещаемость по фото",
    "import_clean": "Импорт клиентов",
    SHORT_TASKS: "Короткие задачи: заявки, сообщения, поиск, напоминания",
}

MONTHS_GENITIVE = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]  # fmt: skip


class AILimitExceeded(AIError):
    """Лимит месяца исчерпан — текст для сотрудника, а не ошибка сервера."""


def enabled_for(organization) -> bool:
    """ИИ доступен центру: ключ есть и опция включена платформой."""
    from .services import is_enabled

    return is_enabled() and bool(getattr(organization, "ai_enabled", False))


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    price = settings.AI_PRICES_USD.get(model)
    if price is None:
        logger.warning("AI price is not configured for model %s", model)
        return Decimal(0)
    per_input, per_output = (Decimal(str(p)) for p in price)
    return (input_tokens * per_input + output_tokens * per_output) / Decimal(1_000_000)


def record(organization, *, feature, model, input_tokens, output_tokens, generation=None):
    return AIUsage.objects.create(
        organization=organization,
        feature=feature,
        model=model or "",
        input_tokens=input_tokens or 0,
        output_tokens=output_tokens or 0,
        cost_usd=cost_usd(model or "", input_tokens or 0, output_tokens or 0),
        generation=generation,
    )


def openai_tokens(response) -> tuple[int, int]:
    usage = getattr(response, "usage", None)
    return (
        int(getattr(usage, "prompt_tokens", 0) or 0),
        int(getattr(usage, "completion_tokens", 0) or 0),
    )


def anthropic_tokens(response) -> tuple[int, int]:
    usage = getattr(response, "usage", None)
    return (
        int(getattr(usage, "input_tokens", 0) or 0),
        int(getattr(usage, "output_tokens", 0) or 0),
    )


def to_kzt(usd) -> int:
    return round(Decimal(usd) * Decimal(str(settings.AI_USD_KZT)))


def month_bounds(organization, now=None):
    """Начало текущего и следующего месяца в часовом поясе центра."""
    tz = ZoneInfo(organization.timezone or "Asia/Almaty")
    local = timezone.localtime(now or timezone.now(), tz)
    start = datetime(local.year, local.month, 1, tzinfo=tz)
    nxt = datetime(local.year + local.month // 12, local.month % 12 + 1, 1, tzinfo=tz)
    return start, nxt


def limit_kzt(organization) -> int:
    own = organization.ai_monthly_limit_kzt
    return own if own is not None else settings.AI_MONTHLY_LIMIT_KZT


def month_rows(organization, now=None):
    start, nxt = month_bounds(organization, now)
    return AIUsage.objects.for_tenant(organization).filter(
        created_at__gte=start, created_at__lt=nxt
    )


def spent_kzt(organization, now=None) -> int:
    total = month_rows(organization, now).aggregate(s=Sum("cost_usd"))["s"] or 0
    return to_kzt(total)


def resets_on(organization, now=None) -> str:
    _, nxt = month_bounds(organization, now)
    return f"{nxt.day} {MONTHS_GENITIVE[nxt.month - 1]}"


def ensure_within_limit(organization, now=None) -> None:
    if spent_kzt(organization, now) >= limit_kzt(organization):
        raise AILimitExceeded(
            f"Лимит ИИ на этот месяц исчерпан — обновится {resets_on(organization, now)}."
        )


def summary(organization, now=None) -> dict:
    """Экран «Расход ИИ» владельца: месяц, лимит, на что ушло."""
    groups: dict[str, dict] = {}
    rows = (
        month_rows(organization, now)
        .values("feature")
        .annotate(
            calls=Count("id"),
            input_tokens=Sum("input_tokens"),
            output_tokens=Sum("output_tokens"),
            cost=Sum("cost_usd"),
        )
    )
    for row in rows:
        key = FEATURE_GROUPS.get(row["feature"], SHORT_TASKS)
        group = groups.setdefault(
            key, {"key": key, "label": GROUP_LABELS[key], "calls": 0, "tokens": 0, "cost": 0}
        )
        group["calls"] += row["calls"]
        group["tokens"] += (row["input_tokens"] or 0) + (row["output_tokens"] or 0)
        group["cost"] += row["cost"] or 0
    by_feature = sorted(
        (
            {**{k: v for k, v in g.items() if k != "cost"}, "cost_kzt": to_kzt(g["cost"])}
            for g in groups.values()
        ),
        key=lambda g: (-g["cost_kzt"], -g["calls"]),
    )
    # Итог — той же функцией, что и проверка лимита: экран и отказ не расходятся.
    spent = spent_kzt(organization, now)
    limit = limit_kzt(organization)
    start, _ = month_bounds(organization, now)
    return {
        "month": start.strftime("%Y-%m"),
        "spent_kzt": spent,
        "limit_kzt": limit,
        "exhausted": spent >= limit,
        "resets_on": resets_on(organization, now),
        # Для экрана: дату форматирует фронт на языке сотрудника.
        "resets_at": month_bounds(organization, now)[1].date().isoformat(),
        "by_feature": by_feature,
    }
