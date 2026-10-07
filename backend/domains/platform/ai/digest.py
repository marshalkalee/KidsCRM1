"""
Еженедельный дайджест владельцу (TRU-163, ТЗ раздел 8): что сделать на
этой неделе — не второй дашборд.

Сборка — фоновая задача: агрегаты (aggregates.py, без людей) → блоки, каждый
блок — шаблон слоя генераций (generations.py) → главное сверху с цифрами →
сравнение с прошлым дайджестом. Цифры в выдаче — только из агрегатов:
модель называет ключи фактов, значения подставляет код.

Расписание: раз в час dispatch() смотрит, у каких центров наступили их
день и час (настройки организации, по умолчанию понедельник 9:00 по
времени центра). Не собрался — остаётся прошлый, повтор через сутки.
"""

import datetime
import logging
import re
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from domains.platform.tenants.models import Organization
from domains.platform.tenants.org_settings import DIGEST_HOUR, DIGEST_WEEKDAY, get_org_setting

from . import aggregates, generations, services, usage
from .models import AIDigest, AIGeneration

logger = logging.getLogger(__name__)

# Блоки дайджеста по порядку: (шаблон из prompts/, заголовок блока).
# Новый блок (TRU-161 «какие группы продвигать», TRU-162 «контент») —
# одна строка здесь, если его шаблон отдаёт {"recommendations": [...]}.
BLOCKS = [
    ("marketing_recommendations", "Что сделать на этой неделе"),
]

# Меньше активных детей — советы были бы догадками, честнее сказать, что
# данных мало (как «данных мало» на дашборде, TRU-113).
MIN_ACTIVE_CHILDREN = 15
HIGHLIGHTS = 4
# Повторное «Обновить» раньше — отдаём текущий, не плодим генерации.
REFRESH_COOLDOWN = datetime.timedelta(minutes=10)
# Не собрался по расписанию — следующая попытка не раньше чем через сутки.
RETRY_AFTER = datetime.timedelta(hours=20)

DONE = (AIDigest.Status.READY, AIDigest.Status.INSUFFICIENT_DATA)
PENDING = (AIDigest.Status.QUEUED, AIDigest.Status.RUNNING)
PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}

SECTIONS = {
    "occupancy": "Заполняемость",
    "conversion": "Воронка",
    "sources": "Источники заявок",
    "rejection_reasons": "Отказы",
    "ages": "Дети по возрасту",
    "money": "Деньги",
    "seasonality": "Сезонность",
}
METRICS = {
    "процент": "заполняемость, %",
    "percent": "заполняемость, %",
    "занято": "занято мест",
    "occupied": "занято мест",
    "мест": "мест",
    "capacity": "мест всего",
    "groups_count": "групп",
    "underfilled_count": "групп с недобором",
    "конверсия_процент": "конверсия, %",
    "итого": "весь центр",
    "значение": "",
}
# Списки, у элементов которых своё имя: само имя списка в подписи лишнее.
COLLECTIONS = {"группы"}

LABELS = {
    "kk": {
        "Заполняемость": "Толымдылық",
        "Воронка": "Сату кезеңдері",
        "Источники заявок": "Өтінім көздері",
        "Отказы": "Бас тартулар",
        "Дети по возрасту": "Балалардың жасы",
        "Деньги": "Қаржы",
        "Сезонность": "Маусымдылық",
        "заполняемость, %": "толымдылық, %",
        "занято мест": "орын бос емес",
        "мест": "орын",
        "мест всего": "барлық орын",
        "групп": "топ",
        "групп с недобором": "толмаған топ",
        "конверсия, %": "конверсия, %",
        "весь центр": "бүкіл орталық",
        "Что сделать на этой неделе": "Осы аптада не істеу керек",
        "прошлый месяц": "өткен ай",
        "этот месяц": "осы ай",
        "заявок": "өтінім",
        "этапы": "кезеңдер",
        "Купил абонемент": "Абонемент сатып алды",
        "Новая": "Жаңа",
        "кандидаты": "үміткерлер",
        "приоритет": "басымдық",
    },
    "en": {
        "Заполняемость": "Occupancy",
        "Воронка": "Sales funnel",
        "Источники заявок": "Lead sources",
        "Отказы": "Rejections",
        "Дети по возрасту": "Children by age",
        "Деньги": "Money",
        "Сезонность": "Seasonality",
        "заполняемость, %": "occupancy, %",
        "занято мест": "occupied spots",
        "мест": "spots",
        "мест всего": "total spots",
        "групп": "groups",
        "групп с недобором": "underfilled groups",
        "конверсия, %": "conversion, %",
        "весь центр": "whole centre",
        "Что сделать на этой неделе": "What to do this week",
        "прошлый месяц": "last month",
        "этот месяц": "this month",
        "заявок": "leads",
        "этапы": "stages",
        "Купил абонемент": "Bought a subscription",
        "Новая": "New",
        "кандидаты": "candidates",
        "приоритет": "priority",
    },
}


class DigestCooldown(services.AIError):
    """«Обновить» нажали слишком рано — текст для сотрудника."""


# --- Подписи фактов --------------------------------------------------------

_PART = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def _human(text: str) -> str:
    return str(text).replace("_", " ")


def _label(value: str, language: str) -> str:
    return LABELS.get(language, {}).get(value, value)


def _display_names(row: dict) -> list[str]:
    """Human-readable row values, never internal ids or stable keys."""
    names = []
    for key, value in row.items():
        normalized = str(key).lower()
        if normalized == "id" or normalized.endswith(("_id", "_key")):
            continue
        if isinstance(value, str) and value.strip() and value not in names:
            names.append(value)
        if len(names) == 2:
            break
    return names


def fact_label(snapshot: dict, key: str, language="ru") -> str:
    """'occupancy.группы[3].процент' → 'Заполняемость · Балет 4–9, Алмалы:
    заполняемость, %'. Имя элемента списка — его строковые поля (группа,
    филиал, источник, месяц) из того же снимка."""
    parts = [(m.group(1), m.group(2)) for m in _PART.finditer(key)]
    labels, node = [], snapshot
    for index, (name, number) in enumerate(parts):
        last = index == len(parts) - 1
        if number is not None:
            node = node[int(number)] if isinstance(node, list) and int(number) < len(node) else {}
            if isinstance(node, dict):
                names = _display_names(node)
                if names:
                    labels.append(", ".join(names))
            continue
        node = node.get(name, {}) if isinstance(node, dict) else {}
        if index == 0:
            labels.append(_label(SECTIONS.get(name, _human(name)), language))
        elif last:
            metric = _label(METRICS.get(name, _human(name)), language)
            return f"{' · '.join(labels)}: {metric}" if metric else " · ".join(labels)
        elif name not in COLLECTIONS:
            # «группы» не пишем — дальше имя самой группы; ряд сезонности
            # («Новых заявок») — пишем, у его элементов только месяц.
            labels.append(_label(METRICS.get(name, _human(name)), language))
    return " · ".join(labels)


# --- Сборка ----------------------------------------------------------------


def active_children(snapshot: dict) -> int:
    return int(((snapshot.get("occupancy") or {}).get("итого") or {}).get("occupied") or 0)


def _signature(item: dict) -> str:
    """Один и тот же совет на разных неделях — по фактам, на которые он
    опирается, а не по формулировке: модель каждый раз пишет по-своему."""
    return "|".join(sorted(e["key"] for e in item["evidence"]))


def _items(result: dict, snapshot: dict, language="ru") -> list:
    rows = []
    for row in result.get("recommendations", []):
        evidence = [
            {**e, "label": fact_label(snapshot, e["key"], language)}
            for e in row.get("evidence", [])
        ]
        item = {**row, "evidence": evidence}
        item["id"] = _signature(item)
        rows.append(item)
    return rows


def compare(content: dict, previous: AIDigest | None) -> dict:
    """Что изменилось с прошлого готового дайджеста: новые и ушедшие советы,
    цифры, которые сдвинулись. Нечего сравнивать — None."""
    if previous is None:
        return None
    before = {item["id"]: item for item in previous.content.get("items", [])}
    now = {item["id"]: item for item in content["items"]}
    old_facts = previous.content.get("facts", {})
    values = [
        {"key": key, "label": label, "before": old_facts[key], "after": value}
        for key, (label, value) in content["fact_labels"].items()
        if key in old_facts and old_facts[key] != value
    ]
    changes = {
        "since": previous.week_start.isoformat(),
        "new": [now[i]["title"] for i in now if i not in before],
        "gone": [before[i]["title"] for i in before if i not in now],
        "values": values,
    }
    changes["unchanged"] = not (changes["new"] or changes["gone"] or values)
    return changes


def compose(organization, results: list, snapshot: dict, previous, language="ru") -> dict:
    blocks, items = [], []
    for key, title, result in results:
        rows = _items(result, snapshot, language)
        blocks.append({"key": key, "title": _label(title, language), "items": rows})
        items.extend(rows)
    highlights = sorted(items, key=lambda r: PRIORITY_RANK.get(r.get("priority"), 3))[:HIGHLIGHTS]
    fact_labels = {e["key"]: (e["label"], e["value"]) for item in items for e in item["evidence"]}
    content = {
        "language": language,
        "highlights": highlights,
        "blocks": blocks,
        "items": items,
        "facts": {key: value for key, (_, value) in fact_labels.items()},
        "fact_labels": fact_labels,
    }
    content["changes"] = compare(content, previous)
    content.pop("fact_labels")
    return content


def _set(digest, **fields):
    for name, value in fields.items():
        setattr(digest, name, value)
    digest.save(update_fields=[*fields, "updated_at"])
    return digest


def _previous(digest):
    return (
        AIDigest.objects.for_tenant(digest.organization)
        .filter(
            status=AIDigest.Status.READY,
            language=digest.language,
            created_at__lt=digest.created_at,
        )
        .first()
    )


def build(digest_id) -> AIDigest:
    """Собрать дайджест (вызывается из Celery). Любой сбой — статус «не
    собрался», а не вечное «собирается»: экран покажет прошлый."""
    digest = AIDigest.objects.select_related("organization").get(pk=digest_id)
    _set(digest, status=AIDigest.Status.RUNNING)
    try:
        return _build(digest)
    except Exception:
        logger.exception("AI digest %s failed", digest.id)
        return _set(
            digest,
            status=AIDigest.Status.FAILED,
            error_detail="Новый дайджест не собрался — повторим завтра.",
        )


def _build(digest) -> AIDigest:
    organization = digest.organization
    if not organization.ai_enabled:
        return _set(digest, status=AIDigest.Status.FAILED, error_detail="ИИ-помощник не подключён.")
    try:
        usage.ensure_within_limit(organization)
    except usage.AILimitExceeded as exc:
        return _set(digest, status=AIDigest.Status.LIMIT_EXHAUSTED, error_detail=str(exc))

    snapshot = aggregates.snapshot(organization)
    children = active_children(snapshot)
    if children < MIN_ACTIVE_CHILDREN:
        # Модель не вызываем вовсе: советы по паре детей — догадки.
        return _set(
            digest,
            status=AIDigest.Status.INSUFFICIENT_DATA,
            content={"active_children": children, "needed": MIN_ACTIVE_CHILDREN},
            ready_at=timezone.now(),
        )

    results, failed = [], []
    for key, title in BLOCKS:
        generation = generations.run(
            generations.create(organization, key, parameters={"language": digest.language}).id
        )
        if generation.status == AIGeneration.Status.SUCCEEDED:
            results.append((key, title, generation.result))
        else:
            failed.append(generations.DEGRADATION_MESSAGES.get(generation.status, ""))
    if not results:
        reason = failed[0] if failed else ""
        text = f"{reason} Новый дайджест не собрался — повторим завтра.".strip()
        return _set(digest, status=AIDigest.Status.FAILED, error_detail=text[:500])
    content = compose(organization, results, snapshot, _previous(digest), digest.language)
    content["failed_blocks"] = len(failed)
    return _set(digest, status=AIDigest.Status.READY, content=content, ready_at=timezone.now())


# --- Запуск ----------------------------------------------------------------


def week_start(organization, now=None) -> datetime.date:
    local = timezone.localtime(now or timezone.now(), ZoneInfo(organization.timezone))
    return local.date() - datetime.timedelta(days=local.weekday())


def _schedule(digest):
    from .tasks import build_ai_digest

    transaction.on_commit(lambda: build_ai_digest.delay(str(digest.id)))
    return digest


def request_refresh(organization, user, language="ru") -> tuple[AIDigest, bool]:
    """Кнопка «Обновить». Уже собирается — тот же дайджест; недавно
    обновляли — текст; лимит исчерпан — текст. (дайджест, создан ли новый)."""
    digests = AIDigest.objects.for_tenant(organization)
    pending = digests.filter(status__in=PENDING, language=language).first()
    if pending:
        return pending, False
    last_manual = digests.filter(trigger=AIDigest.Trigger.MANUAL, language=language).first()
    if last_manual and timezone.now() - last_manual.created_at < REFRESH_COOLDOWN:
        minutes = int((timezone.now() - last_manual.created_at).total_seconds() // 60)
        raise DigestCooldown(
            f"Дайджест обновляли {minutes} мин назад — данные с тех пор почти не изменились."
        )
    usage.ensure_within_limit(organization)
    digest = AIDigest.objects.create(
        organization=organization,
        week_start=week_start(organization),
        trigger=AIDigest.Trigger.MANUAL,
        requested_by=user,
        language=language,
    )
    return _schedule(digest), True


def due(organization, now=None) -> bool:
    """Наступил ли день и час дайджеста этой недели и не собран ли он уже."""
    now = now or timezone.now()
    tz = ZoneInfo(organization.timezone)
    start = week_start(organization, now)
    weekday = get_org_setting(organization, DIGEST_WEEKDAY)
    hour = get_org_setting(organization, DIGEST_HOUR)
    moment = datetime.datetime.combine(
        start + datetime.timedelta(days=weekday), datetime.time(hour), tzinfo=tz
    )
    if now < moment:
        return False
    digests = AIDigest.objects.for_tenant(organization)
    if digests.filter(created_at__gte=moment, status__in=(*DONE, *PENDING)).exists():
        return False
    failed = digests.filter(week_start=start, trigger=AIDigest.Trigger.SCHEDULE).first()
    return not (failed and now - failed.created_at < RETRY_AFTER)


def dispatch(now=None) -> int:
    """Раз в час из Celery beat: поставить дайджест центрам, у которых пора."""
    if not (services.is_enabled() or settings.AI_FIXTURE_MODE):
        return 0
    started = 0
    for organization in Organization.objects.filter(is_active=True, ai_enabled=True):
        if not due(organization, now):
            continue
        previous_language = (
            AIDigest.objects.for_tenant(organization)
            .filter(status=AIDigest.Status.READY)
            .values_list("language", flat=True)
            .first()
            or "ru"
        )
        digest = AIDigest.objects.create(
            organization=organization,
            week_start=week_start(organization, now),
            trigger=AIDigest.Trigger.SCHEDULE,
            language=previous_language,
        )
        _schedule(digest)
        started += 1
    return started
