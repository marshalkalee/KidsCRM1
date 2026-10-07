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
    ("group_promotion", "Какие группы продвигать"),
]

# Меньше активных детей — советы были бы догадками, честнее сказать, что
# данных мало (как «данных мало» на дашборде, TRU-113).
MIN_ACTIVE_CHILDREN = 15
HIGHLIGHTS = 4
# Повторное «Обновить» раньше — отдаём текущий, не плодим генерации.
REFRESH_COOLDOWN = datetime.timedelta(minutes=10)
# Не собрался по расписанию — следующая попытка не раньше чем через сутки.
RETRY_AFTER = datetime.timedelta(hours=20)
# Сборка — два вызова модели, обычно меньше минуты. Висит дольше — задача
# потерялась (воркер лежал, брокер перезапустился): считаем «не собрался»,
# иначе «Обновить» вечно отдавал бы этот же и новый не ставился.
STUCK_AFTER = datetime.timedelta(minutes=15)

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
    "promotion_opportunities": "Продвижение",
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
    "заполняемость_процент": "заполняемость, %",
    "свободных_мест": "свободных мест",
    "вместимость": "мест всего",
    "заявок_на_направление": "заявок на направление",
    "возраст_от": "возраст от",
    "возраст_до": "возраст до",
    "итого": "весь центр",
    "значение": "",
}
# Списки, у элементов которых своё имя: само имя списка в подписи лишнее.
COLLECTIONS = {"группы", "кандидаты"}
# Поля элемента, из которых его имя, — по порядку; иначе первые строковые поля.
NAME_FIELDS = ("группа", "филиал", "источник", "месяц", "причина")
# Служебный идентификатор (псевдоним группы) — в подпись не попадает.
_REF = re.compile(r"^[0-9a-f]{12,}$")


class DigestCooldown(services.AIError):
    """«Обновить» нажали слишком рано — текст для сотрудника."""


# --- Подписи фактов --------------------------------------------------------

_PART = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def _human(text: str) -> str:
    return str(text).replace("_", " ")


def _item_names(node: dict) -> list:
    names = [str(node[f]) for f in NAME_FIELDS if isinstance(node.get(f), str)]
    if not names:
        names = [v for v in node.values() if isinstance(v, str) and not _REF.match(v)]
    return names[:2]


def fact_label(snapshot: dict, key: str) -> str:
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
                names = _item_names(node)
                if names:
                    labels.append(", ".join(names))
            continue
        node = node.get(name, {}) if isinstance(node, dict) else {}
        if index == 0:
            labels.append(SECTIONS.get(name, _human(name)))
        elif last:
            metric = METRICS.get(name, _human(name))
            return f"{' · '.join(labels)}: {metric}" if metric else " · ".join(labels)
        elif name not in COLLECTIONS:
            # «группы» не пишем — дальше имя самой группы; ряд сезонности
            # («Новых заявок») — пишем, у его элементов только месяц.
            labels.append(METRICS.get(name, _human(name)))
    return " · ".join(labels)


# --- Сборка ----------------------------------------------------------------


def active_children(snapshot: dict) -> int:
    return int(((snapshot.get("occupancy") or {}).get("итого") or {}).get("occupied") or 0)


def _signature(item: dict) -> str:
    """Один и тот же совет на разных неделях — по фактам, на которые он
    опирается, а не по формулировке: модель каждый раз пишет по-своему."""
    return "|".join(sorted(e["key"] for e in item["evidence"]))


def _from_group_promotion(row: dict) -> dict:
    """Блок TRU-161 отдаёт группу-кандидата и её цифры (basis), а не ключи
    фактов: приводим к общему виду совета. Цифры — те же, что посчитал код
    шаблона из агрегатов, модель их не пишет."""
    key = row["candidate_key"]
    place = f"{row['group']}, {row['branch']}"
    basis = row.get("basis") or {}
    facts = [
        ("available_places", "свободных мест"),
        ("occupancy_percent", "заполняемость, %"),
        ("conversion_percent", "конверсия заявок направления, %"),
    ]
    return {
        "title": row["title"],
        "rationale": row["rationale"],
        "action": row["action"],
        "priority": "high" if row.get("systemic") else "medium",
        "evidence": [
            {
                "key": f"group_promotion.{key}.{name}",
                "label": f"{place}: {label}",
                "value": basis[name],
            }
            for name, label in facts
            if isinstance(basis.get(name), int | float)
        ],
    }


# Блоки со своим форматом ответа → общий вид совета дайджеста.
ADAPTERS = {"group_promotion": _from_group_promotion}


def _items(result: dict, snapshot: dict, block: str = "") -> list:
    rows = []
    adapt = ADAPTERS.get(block)
    for row in result.get("recommendations", []):
        if adapt:
            row = adapt(row)
            item = {**row, "id": _signature(row)}
            rows.append(item)
            continue
        evidence = [{**e, "label": fact_label(snapshot, e["key"])} for e in row.get("evidence", [])]
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


def compose(organization, results: list, snapshot: dict, previous) -> dict:
    blocks, items = [], []
    for key, title, result in results:
        rows = _items(result, snapshot, key)
        blocks.append({"key": key, "title": title, "items": rows})
        items.extend(rows)
    highlights = sorted(items, key=lambda r: PRIORITY_RANK.get(r.get("priority"), 3))[:HIGHLIGHTS]
    fact_labels = {e["key"]: (e["label"], e["value"]) for item in items for e in item["evidence"]}
    content = {
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
        .filter(status=AIDigest.Status.READY, created_at__lt=digest.created_at)
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
        generation = generations.run(generations.create(organization, key).id)
        if generation.status == AIGeneration.Status.SUCCEEDED:
            results.append((key, title, generation.result))
        else:
            failed.append(generations.DEGRADATION_MESSAGES.get(generation.status, ""))
    if not results:
        reason = failed[0] if failed else ""
        text = f"{reason} Новый дайджест не собрался — повторим завтра.".strip()
        return _set(digest, status=AIDigest.Status.FAILED, error_detail=text[:500])
    content = compose(organization, results, snapshot, _previous(digest))
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


def expire_stuck(organization, now=None) -> int:
    """Сборка висит дольше STUCK_AFTER — «не собрался»: экран покажет прошлый
    с пояснением, «Обновить» и расписание поставят новый."""
    border = (now or timezone.now()) - STUCK_AFTER
    return (
        AIDigest.objects.for_tenant(organization)
        .filter(status__in=PENDING, created_at__lt=border)
        .update(
            status=AIDigest.Status.FAILED,
            error_detail="Дайджест не собрался — нажмите «Обновить», чтобы собрать заново.",
            updated_at=timezone.now(),
        )
    )


def request_refresh(organization, user) -> tuple[AIDigest, bool]:
    """Кнопка «Обновить». Уже собирается — тот же дайджест; недавно
    обновляли — текст; лимит исчерпан — текст. (дайджест, создан ли новый)."""
    expire_stuck(organization)
    digests = AIDigest.objects.for_tenant(organization)
    pending = digests.filter(status__in=PENDING).first()
    if pending:
        return pending, False
    last_manual = digests.filter(trigger=AIDigest.Trigger.MANUAL).first()
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
    expire_stuck(organization, now)
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
        digest = AIDigest.objects.create(
            organization=organization,
            week_start=week_start(organization, now),
            trigger=AIDigest.Trigger.SCHEDULE,
        )
        _schedule(digest)
        started += 1
    return started
