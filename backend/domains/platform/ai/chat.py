# ruff: noqa: E501 — промпты и описания инструментов: связный текст, резать строки ради длины хуже для чтения.
"""
Чат с ИИ на главной: «что у нас с долгами в Орбите?», «кто не пришёл
вчера?», «сколько заработали в сентябре?» — ответ по живым данным CRM.

Как ИИ знает, что происходит: у него есть инструменты, и каждый — это
GET к тому же API, на котором работают экраны, от имени того, кто
спрашивает. Поэтому:
- данные всегда текущие, без отдельной копии и без «переобучения»;
- ИИ видит ровно то, что этот сотрудник видит на сайте: права, филиалы
  управляющего, изоляция организаций — те же проверки, что у экранов;
- цифры совпадают с экранами — их считает тот же код.

Только чтение: изменить что-то через чат нельзя. Телефоны, почта и фото
в модель не уходят (вырезаются из ответов), как и в остальных
ИИ-функциях. Чат только у руководителей (role_permissions.can_use_ai_chat).

История переписки не хранится на сервере: экран присылает последние
сообщения, ИИ при необходимости заново смотрит данные.
"""

import datetime
import json
import logging
import re
import uuid
from collections import Counter

from django.conf import settings
from django.urls import Resolver404, resolve
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from . import services
from .services import AIError

logger = logging.getLogger(__name__)

MAX_HISTORY = 20
MAX_MESSAGE_CHARS = 2000
MAX_TOOL_ROUNDS = 8
MAX_TOOL_CHARS = 16000
MAX_LIST_ITEMS = 40

# Телефоны, почта, фото — не в модель. Ключ ответа API совпал — поле убрано.
HIDDEN_KEYS = re.compile(r"phone|whatsapp|email|photo|avatar|password|token", re.IGNORECASE)
# Служебное для экранов, модели только мешает и съедает место.
NOISE_KEYS = re.compile(
    r"^(organization|updated_at|deleted_at|next|previous|permissions|allowed_transitions|show_money"
    r"|schema_version|message_text|reminder_text|color"
    # «Мало истории для трендов» — для экрана; модель принимает это за «данных нет».
    r"|enough_data|days_until_enough|data_since|min_history_days)$|_color$"
)

_factory = APIRequestFactory()


class Viewer:
    """Кто смотрит данные: сотрудник и хост, с которого он пришёл (для
    ссылок пагинации во вьюхах)."""

    def __init__(self, user, host="localhost"):
        self.user = user
        self.host = host


def _keep(key, value, siblings) -> bool:
    if HIDDEN_KEYS.search(key) or NOISE_KEYS.search(key):
        return False
    if value is None or value == "" or value == []:
        return False
    # branch=<uuid> рядом с branch_name — модели хватит имени.
    if not key.endswith("id") and f"{key}_name" in siblings:
        return False
    # starts_at рядом с starts_at_local — одно и то же время.
    return f"{key}_local" not in siblings


def _shrink(value):
    """Ответ API → то, что можно показать модели: без контактов, фото и
    служебных полей, длинные списки обрезаны с пометкой, сколько всего."""
    if isinstance(value, dict):
        return {k: _shrink(v) for k, v in value.items() if _keep(str(k), v, value)}
    if isinstance(value, list):
        items = [_shrink(v) for v in value[:MAX_LIST_ITEMS]]
        if len(value) > MAX_LIST_ITEMS:
            items.append({"_обрезано": f"показано {MAX_LIST_ITEMS} из {len(value)}"})
        return items
    return value


def api_get(viewer: Viewer, path: str, params: dict | None = None, *, raw=False):
    """GET /api/v1/<path> от имени сотрудника — тем же путём, что запрос
    экрана (права и фильтры вьюхи), без HTTP. Нет доступа — понятный ответ."""
    user = viewer.user
    params = {k: v for k, v in (params or {}).items() if v not in (None, "", [])}
    url = f"/api/v1/{path}"
    try:
        match = resolve(url)
    except Resolver404:
        return {"ошибка": "нет такого раздела"}
    request = _factory.get(url, params, HTTP_HOST=viewer.host)
    request.organization = user.organization
    force_authenticate(request, user=user)
    response = match.func(request, *match.args, **match.kwargs)
    if response.status_code in (401, 403):
        return {"ошибка": "у этого сотрудника нет доступа к этим данным"}
    if response.status_code == 404:
        return {"ошибка": "не найдено"}
    if response.status_code >= 400:
        return {"ошибка": f"запрос не прошёл ({response.status_code})", "детали": response.data}
    return response.data if raw else _shrink(response.data)


def _pick(data, fields):
    """Из списка (или {"results": [...]}) — только нужные поля строк."""
    rows = data.get("results") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return data
    picked = [{k: row[k] for k in fields if k in row} for row in rows if isinstance(row, dict)]
    return {**data, "results": picked} if isinstance(data, dict) else picked


LEAD_FIELDS = (
    "id",
    "kind_label",
    "parent_name",
    "child_name",
    "child_age",
    "branch_name",
    "direction_name",
    "source_name",
    "assigned_to_name",
    "status_label",
    "days_in_status",
    "is_stale",
    "created_at",
    "rejection_reason_name",
)
GROUP_FIELDS = (
    "id",
    "name",
    "branch_name",
    "direction_name",
    "teachers_detail",
    "capacity",
    "members_count",
    "fill_percent",
    "is_underfilled",
    "age_min",
    "age_max",
    "status",
    "schedule",
)


def _lesson_row(row):
    starts, ends = str(row.get("starts_at_local") or ""), str(row.get("ends_at_local") or "")
    names = row.get("individual_children_names") or []
    return {
        "id": row.get("id"),
        "когда": f"{starts[:10]} {starts[11:16]}–{ends[11:16]}",
        "группа": row.get("group_name") or ("индивидуальное: " + ", ".join(names) if names else ""),
        "педагог": row.get("teacher_name"),
        "зал": row.get("room_name"),
        "статус": row.get("status_display"),
        "детей": f"{row.get('total_participants_count', 0)}/{row.get('capacity') or '—'}",
        "пробных": row.get("trial_count") or None,
        "отмена": row.get("cancel_reason") or None,
    }


def _lessons(viewer, a):
    """Занятия за даты + итоги по всем (педагоги, дни, статусы): строк за
    неделю больше, чем влезает модели, а считать «кто ведёт больше» надо
    по всем, не по первым сорока."""
    keys = ("date_from", "date_to", "branch", "teacher", "group", "status")
    data = api_get(viewer, "schedule/", {k: a.get(k) for k in keys}, raw=True)
    rows = (
        data if isinstance(data, list) else data.get("results") if isinstance(data, dict) else None
    )
    if not isinstance(rows, list):
        return _shrink(data)
    return {
        "итоги": {
            "всего занятий": len(rows),
            "по педагогам": dict(Counter(r.get("teacher_name") or "—" for r in rows).most_common()),
            "по статусам": dict(Counter(r.get("status_display") or "—" for r in rows)),
            "по дням": dict(
                sorted(Counter(str(r.get("starts_at_local") or "")[:10] for r in rows).items())
            ),
        },
        "занятия": _shrink([_lesson_row(r) for r in rows]),
    }


def _id(value) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except ValueError as exc:
        raise ValueError("id должен быть UUID из ответа другого инструмента") from exc


PERIOD = {
    "period": {
        "type": "string",
        "enum": ["today", "week", "month", "quarter", "year", "custom"],
        "description": "Период до сегодня включительно: today; week — с понедельника; month — с 1-го числа текущего месяца; quarter; year. Прошлый месяц или любые даты — custom с from и to.",
    },
    "from": {"type": "string", "description": "Начало периода, YYYY-MM-DD (для custom)."},
    "to": {"type": "string", "description": "Конец периода, YYYY-MM-DD (для custom)."},
    "branch": {"type": "string", "description": "id филиала (из branches), пусто — все доступные."},
}


def _tool(name, description, properties=None, required=None, run=None):
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties or {},
            "required": required or [],
            "additionalProperties": False,
        },
        "run": run,
    }


def _flags(args, *names):
    return {n: "1" for n in names if args.get(n)}


TOOLS = [
    _tool(
        "attention_today",
        "Что требует внимания прямо сейчас: новые заявки без звонка, вчерашние занятия без отметки, просроченные долги, дети без абонемента — с количеством и суммами. Начинай с этого на общие вопросы «что у нас происходит».",
        run=lambda user, a: api_get(user, "notifications/"),
    ),
    _tool(
        "branches",
        "Филиалы организации (id, название, адрес) — чтобы фильтровать другие инструменты по филиалу.",
        run=lambda user, a: api_get(user, "branches/"),
    ),
    _tool(
        "directions",
        "Направления (балет, гимнастика и т.п.) с id.",
        run=lambda user, a: api_get(user, "directions/"),
    ),
    _tool(
        "staff",
        "Сотрудники: имя, роль (owner, manager, admin, accountant, teacher), филиалы.",
        run=lambda user, a: api_get(user, "users/"),
    ),
    _tool(
        "search",
        "Быстрый поиск по имени ребёнка, родителя или заявки. Возвращает id для карточек.",
        {"q": {"type": "string", "description": "Имя или часть имени."}},
        ["q"],
        run=lambda user, a: api_get(user, "clients/search/", {"q": a.get("q")}),
    ),
    _tool(
        "children",
        "Список детей с фильтрами: статус, филиал, направление, группа, долг, абонемент заканчивается, без абонемента. Даёт общее количество (count) и строки.",
        {
            "q": {"type": "string", "description": "Поиск по имени ребёнка или родителя."},
            "status": {
                "type": "string",
                "enum": ["trial", "active", "paused", "left"],
                "description": "trial — пробный, active — ходит, paused — приостановлен, left — ушёл.",
            },
            "branch": {"type": "string"},
            "direction": {"type": "string"},
            "group": {"type": "string"},
            "has_debt": {"type": "boolean"},
            "debt_overdue": {"type": "boolean"},
            "expiring": {"type": "boolean", "description": "Абонемент скоро заканчивается."},
            "no_subscription": {"type": "boolean"},
            "page_size": {"type": "integer", "description": "Сколько строк вернуть, до 50."},
        },
        run=lambda user, a: api_get(
            user,
            "clients/children/table/",
            {
                "q": a.get("q"),
                "status": a.get("status"),
                "branch": a.get("branch"),
                "direction": a.get("direction"),
                "group": a.get("group"),
                "page_size": min(int(a.get("page_size") or 25), 50),
                **_flags(a, "has_debt", "debt_overdue", "expiring", "no_subscription"),
            },
        ),
    ),
    _tool(
        "child_card",
        "Карточка ребёнка: родители, группы, абонементы, долг, медицинские заметки, последние события.",
        {"child_id": {"type": "string"}},
        ["child_id"],
        run=lambda user, a: api_get(user, f"clients/children/{_id(a['child_id'])}/card/"),
    ),
    _tool(
        "child_payments",
        "История оплат ребёнка (включая отменённые).",
        {"child_id": {"type": "string"}},
        ["child_id"],
        run=lambda user, a: api_get(user, "payments/", {"child_id": _id(a["child_id"])}),
    ),
    _tool(
        "child_attendance",
        "Посещения ребёнка: занятия и отметки.",
        {"child_id": {"type": "string"}},
        ["child_id"],
        run=lambda user, a: api_get(user, "attendance/history/", {"child": _id(a["child_id"])}),
    ),
    _tool(
        "parent_card",
        "Карточка родителя: дети, общий долг, последние оплаты.",
        {"parent_id": {"type": "string"}},
        ["parent_id"],
        run=lambda user, a: api_get(user, f"clients/parents/{_id(a['parent_id'])}/card/"),
    ),
    _tool(
        "debtors",
        "Должники (как экран «Задолженности»): ребёнок, абонемент, сумма долга, сколько дней долг, итог.",
        {
            "branch": {"type": "string"},
            "direction": {"type": "string"},
            "overdue": {"type": "boolean", "description": "Только просроченные."},
            "q": {"type": "string"},
        },
        run=lambda user, a: api_get(
            user,
            "subscriptions/debtors/",
            {
                "branch": a.get("branch"),
                "direction": a.get("direction"),
                "q": a.get("q"),
                **_flags(a, "overdue"),
            },
        ),
    ),
    _tool(
        "renewals",
        "Абонементы, которые заканчиваются (экран «Продления»): кто, когда, сколько занятий осталось, звонили ли.",
        {
            "branch": {"type": "string"},
            "direction": {"type": "string"},
            "not_contacted": {"type": "boolean"},
            "q": {"type": "string"},
        },
        run=lambda user, a: api_get(
            user,
            "subscriptions/renewals/",
            {
                "branch": a.get("branch"),
                "direction": a.get("direction"),
                "q": a.get("q"),
                **_flags(a, "not_contacted"),
            },
        ),
    ),
    _tool(
        "lessons",
        "Занятия (расписание) за даты: итоги (сколько всего, по педагогам, по дням, по статусам) и строки — время, группа, педагог, зал, статус, сколько детей.",
        {
            "date_from": {"type": "string", "description": "YYYY-MM-DD"},
            "date_to": {"type": "string", "description": "YYYY-MM-DD"},
            "branch": {"type": "string"},
            "teacher": {"type": "string", "description": "id педагога (из staff)."},
            "group": {"type": "string"},
            "status": {"type": "string"},
        },
        ["date_from", "date_to"],
        run=_lessons,
    ),
    _tool(
        "unmarked_yesterday",
        "Вчерашние занятия, где не отмечена посещаемость.",
        run=lambda user, a: api_get(user, "attendance/unmarked-yesterday/"),
    ),
    _tool(
        "groups",
        "Группы: направление, филиал, педагог, вместимость и сколько детей.",
        {
            "branch": {"type": "string"},
            "direction": {"type": "string"},
            "teacher": {"type": "string"},
        },
        run=lambda user, a: _pick(
            api_get(user, "groups/", {k: a.get(k) for k in ("branch", "direction", "teacher")}),
            GROUP_FIELDS,
        ),
    ),
    _tool(
        "group_members",
        "Дети в группе.",
        {"group_id": {"type": "string"}},
        ["group_id"],
        run=lambda user, a: api_get(user, f"groups/{_id(a['group_id'])}/members/"),
    ),
    _tool(
        "leads",
        "Заявки (продажи): имя, ребёнок, статус, источник, дата. kind=new — новые клиенты, renewal — продления.",
        {
            "q": {"type": "string"},
            "status": {
                "type": "string",
                "enum": [
                    "new",
                    "contacted",
                    "trial_scheduled",
                    "trial_attended",
                    "purchased",
                    "thinking",
                    "rejected",
                ],
                "description": "new — новая, contacted — связались, trial_scheduled — записан на пробное, trial_attended — пришёл на пробное, purchased — купил, thinking — думает, rejected — отказ.",
            },
            "kind": {"type": "string", "enum": ["new", "renewal"]},
            "created_from": {"type": "string", "description": "YYYY-MM-DD"},
            "created_to": {"type": "string", "description": "YYYY-MM-DD"},
        },
        run=lambda user, a: _pick(
            api_get(
                user,
                "leads/",
                {
                    **{k: a.get(k) for k in ("q", "status", "kind", "created_from", "created_to")},
                    "limit": 40,
                },
            ),
            LEAD_FIELDS,
        ),
    ),
    _tool(
        "lead",
        "Заявка подробно: история, комментарии, пробное.",
        {"lead_id": {"type": "string"}},
        ["lead_id"],
        run=lambda user, a: {
            "заявка": api_get(user, f"leads/{_id(a['lead_id'])}/"),
            "комментарии": api_get(user, f"leads/{_id(a['lead_id'])}/comments/"),
        },
    ),
    _tool(
        "analytics_catalog",
        "Какие метрики аналитики есть (выручка, посещаемость, конверсии, отток и т.п.) и по каким разрезам их можно разбить. Вызови перед metrics/breakdown, если не знаешь имени метрики.",
        run=lambda user, a: api_get(user, "analytics/catalog/"),
    ),
    _tool(
        "metrics",
        "Значения метрик за период с прошлым периодом для сравнения. Например выручка за месяц.",
        {
            "metrics": {
                "type": "string",
                "description": "Имена метрик через запятую (из analytics_catalog).",
            },
            **PERIOD,
        },
        ["metrics"],
        run=lambda user, a: api_get(
            user,
            "analytics/metrics/",
            {"metrics": a.get("metrics"), "series": "0", **{k: a.get(k) for k in PERIOD}},
        ),
    ),
    _tool(
        "breakdown",
        "Метрика в разрезе: по филиалам, направлениям, педагогам, способам оплаты и т.п. (by — из analytics_catalog).",
        {"metric": {"type": "string"}, "by": {"type": "string"}, **PERIOD},
        ["metric", "by"],
        run=lambda user, a: api_get(
            user,
            "analytics/breakdown/",
            {"metric": a.get("metric"), "by": a.get("by"), **{k: a.get(k) for k in PERIOD}},
        ),
    ),
    _tool(
        "sales_funnel",
        "Воронка продаж за период. funnel.total — сколько всего заявок пришло за период; stages[].count — сколько из них дошли до этапа; stages[].current — сколько заявок сейчас стоят на этом этапе (не за период!).",
        dict(PERIOD),
        run=lambda user, a: api_get(user, "analytics/funnel/", {k: a.get(k) for k in PERIOD}),
    ),
    _tool(
        "lead_sources",
        "Источники заявок за период: по каждому — сколько заявок (leads), дошли до пробного, купили, конверсия, выручка.",
        dict(PERIOD),
        run=lambda user, a: api_get(user, "analytics/sources/", {k: a.get(k) for k in PERIOD}),
    ),
    _tool(
        "group_occupancy",
        "Заполненность групп: места, занято, процент.",
        dict(PERIOD),
        run=lambda user, a: api_get(
            user, "analytics/group-occupancy/", {k: a.get(k) for k in PERIOD}
        ),
    ),
]
TOOLS_BY_NAME = {t["name"]: t for t in TOOLS}

# Что показать под ответом: «Посмотрел: долги, расписание».
TOOL_LABELS = {
    "attention_today": "что требует внимания",
    "branches": "филиалы",
    "directions": "направления",
    "staff": "сотрудники",
    "search": "поиск",
    "children": "дети",
    "child_card": "карточка ребёнка",
    "child_payments": "оплаты",
    "child_attendance": "посещения",
    "parent_card": "карточка родителя",
    "debtors": "задолженности",
    "renewals": "продления",
    "lessons": "расписание",
    "unmarked_yesterday": "посещаемость",
    "groups": "группы",
    "group_members": "состав группы",
    "leads": "заявки",
    "lead": "заявка",
    "analytics_catalog": "аналитика",
    "metrics": "аналитика",
    "breakdown": "аналитика",
    "sales_funnel": "воронка продаж",
    "lead_sources": "источники заявок",
    "group_occupancy": "заполненность групп",
}


def _references(organization):
    """Фильтры, куда модель иногда пишет название вместо id: модель и поле имени."""
    from domains.platform.tenants.models import Branch, Direction
    from domains.platform.users.models import User
    from domains.scheduling.groups.models import Group

    return {
        "branch": (Branch.objects.for_tenant(organization), "name"),
        "direction": (Direction.objects.for_tenant(organization), "name"),
        "group": (Group.objects.for_tenant(organization), "name"),
        "teacher": (User.objects.filter(organization=organization), "full_name"),
    }


def _resolve_refs(organization, args: dict) -> dict:
    """«Алмалы» → id филиала. Не нашли одно совпадение — понятная ошибка
    модели, а не 500 от вьюхи."""
    refs = None
    resolved = dict(args)
    for key, value in args.items():
        if key not in ("branch", "direction", "group", "teacher") or not value:
            continue
        try:
            resolved[key] = str(uuid.UUID(str(value)))
            continue
        except ValueError:
            pass
        refs = refs or _references(organization)
        qs, field = refs[key]
        matches = list(
            qs.filter(**{f"{field}__iexact": str(value).strip()}).values_list("id", flat=True)[:2]
        )
        if len(matches) != 1:
            matches = list(
                qs.filter(**{f"{field}__icontains": str(value).strip()}).values_list(
                    "id", flat=True
                )[:2]
            )
        if len(matches) != 1:
            raise ValueError(
                f"{key}: «{value}» не найден однозначно — возьми id из branches, directions, groups или staff"
            )
        resolved[key] = str(matches[0])
    return resolved


def run_tool(viewer: Viewer, name: str, args: dict) -> str:
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        result = {"ошибка": f"нет инструмента {name}"}
    else:
        try:
            args = _resolve_refs(viewer.user.organization, args or {})
            result = tool["run"](viewer, args)
        except (ValueError, KeyError, TypeError) as exc:
            result = {"ошибка": str(exc) or "неверные параметры"}
        except Exception:  # noqa: BLE001 — сбой одного инструмента не роняет ответ
            logger.exception("AI chat tool %s failed", name)
            result = {"ошибка": "не удалось получить данные"}
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) > MAX_TOOL_CHARS:
        text = text[:MAX_TOOL_CHARS] + "… [ответ обрезан — уточни фильтры]"
    return text


SYSTEM = """Ты — ИИ-помощник в CRM детского центра «{org}» (танцы, спорт, кружки; Казахстан, деньги в тенге ₸). Тебе пишет {name}, роль: {role}.
Сегодня {today} ({weekday}), часовой пояс центра {tz}. «Эта неделя» — {week_start}…{week_end} (пн–вс), «этот месяц» — {month_start}…{month_end}, «прошлый месяц» — {prev_start}…{prev_end}.

Отвечай по живым данным CRM: прежде чем назвать цифру, имя или список — посмотри инструментами. Не выдумывай и не угадывай. Если данных нет или нет доступа — так и скажи.
Количества и суммы за период бери из аналитики (metrics, breakdown, sales_funnel, lead_sources), а не считай строки списков — списки обрезаются. Цифры бери ровно как в данных инструментов, не пересчитывай суммы вручную, если итог уже есть. Деньги пиши с пробелами между тысячами: 45 000 ₸, 2 407 500 ₸. «Больше всех», «меньше всех» — если у нескольких одинаковое значение, назови всех.
Период «в сентябре», «за прошлый месяц» — это period=custom с from/to (первое и последнее число месяца); period=month — только текущий месяц с 1-го числа по сегодня.
Отвечай на языке вопроса (русский, казахский или английский), коротко и по делу: сначала ответ, потом детали. Списки — маркерами, до 10 строк; если больше — скажи, сколько всего, и предложи открыть экран.
Можно ставить ссылки на экраны CRM в формате Markdown [текст](/путь): ребёнок /children/<id>, родитель /parents/<id>, заявка /leads/<id>, группа /groups/<id>, экраны /debts, /renewals, /leads, /schedule, /attendance, /analytics. Только эти пути и только id из данных.
Телефонов и почты у тебя нет — если спрашивают контакты, дай ссылку на карточку.
Ты только читаешь данные: ничего не меняешь, оплаты не принимаешь, сообщений не отправляешь. Если просят сделать действие — подскажи, где это сделать в CRM."""

WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
ROLES = {
    "owner": "владелец",
    "manager": "управляющий",
    "admin": "администратор",
    "accountant": "бухгалтер",
    "teacher": "педагог",
}


def _system(user) -> str:
    org = user.organization
    tz_name = org.timezone or "Asia/Almaty"
    now = timezone.now().astimezone(timezone.zoneinfo.ZoneInfo(tz_name))
    today = now.date()
    week_start = today - datetime.timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    next_month = (month_start + datetime.timedelta(days=32)).replace(day=1)
    prev_end = month_start - datetime.timedelta(days=1)
    return SYSTEM.format(
        week_start=week_start.isoformat(),
        week_end=(week_start + datetime.timedelta(days=6)).isoformat(),
        month_start=month_start.isoformat(),
        month_end=(next_month - datetime.timedelta(days=1)).isoformat(),
        prev_start=prev_end.replace(day=1).isoformat(),
        prev_end=prev_end.isoformat(),
        org=org.name,
        name=user.full_name or "сотрудник",
        role=ROLES.get(user.role, user.role),
        today=now.date().isoformat(),
        weekday=WEEKDAYS[now.weekday()],
        tz=tz_name,
    )


def _clean_history(messages) -> list[dict]:
    history = []
    for m in (messages or [])[-MAX_HISTORY:]:
        role = m.get("role") if isinstance(m, dict) else None
        content = (m.get("content") or "").strip() if isinstance(m, dict) else ""
        if role in ("user", "assistant") and content:
            history.append({"role": role, "content": content[:MAX_MESSAGE_CHARS]})
    # Модели ждут, что разговор начинается с вопроса и им заканчивается.
    while history and history[0]["role"] != "user":
        history.pop(0)
    if not history or history[-1]["role"] != "user":
        raise AIError("Напишите вопрос.")
    return history


def ask(user, messages, *, host="localhost") -> dict:
    """Ответ на последний вопрос переписки: {"answer", "sources"}."""
    if not services.is_enabled():
        raise AIError("ИИ-помощник не настроен.")
    history = _clean_history(messages)
    used: list[str] = []
    run = _ask_openai if services.provider() == "openai" else _ask_anthropic
    answer = run(Viewer(user, host), history, used)
    sources = list(dict.fromkeys(TOOL_LABELS.get(n, n) for n in used))
    return {
        "answer": answer.strip() or "Не получилось ответить — переформулируйте вопрос.",
        "sources": sources,
    }


def _too_long():
    return AIError("Вопрос потребовал слишком много данных — уточните: филиал, период или имя.")


def _ask_anthropic(viewer, history, used) -> str:
    import anthropic

    tools = [
        {"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
        for t in TOOLS
    ]
    messages = list(history)
    for _ in range(MAX_TOOL_ROUNDS):
        try:
            response = services._client().beta.messages.create(
                model=settings.AI_MODEL,
                max_tokens=4000,
                betas=[services.FALLBACK_BETA],
                fallbacks="default",
                system=_system(viewer.user),
                tools=tools,
                messages=messages,
                output_config={"effort": "low"},
            )
        except anthropic.RateLimitError as exc:
            raise AIError("ИИ сейчас перегружен — попробуйте через минуту.") from exc
        except anthropic.APIStatusError as exc:
            logger.error("AI chat API error %s: %s", exc.status_code, exc.message)
            raise AIError("ИИ временно недоступен.") from exc
        except anthropic.APIConnectionError as exc:
            raise AIError("Нет связи с ИИ — проверьте интернет.") from exc

        if response.stop_reason == "refusal":
            raise AIError("ИИ не стал отвечать на этот вопрос.")
        if response.stop_reason != "tool_use":
            return "".join(b.text for b in response.content if b.type == "text")
        messages.append({"role": "assistant", "content": [_block(b) for b in response.content]})
        results = []
        for block in response.content:
            if block.type == "tool_use":
                used.append(block.name)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": run_tool(viewer, block.name, block.input),
                    }
                )
        messages.append({"role": "user", "content": results})
    raise _too_long()


def _block(block) -> dict:
    """Блок ответа Claude обратно в историю — как есть (текст, вызов
    инструмента, мысли — с подписью)."""
    if hasattr(block, "model_dump"):
        return block.model_dump(exclude_none=True)
    return {k: v for k, v in vars(block).items() if v is not None}


def _ask_openai(viewer, history, used) -> str:
    import openai

    tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            },
        }
        for t in TOOLS
    ]
    messages = [{"role": "system", "content": _system(viewer.user)}, *history]
    for _ in range(MAX_TOOL_ROUNDS):
        try:
            response = services._openai_client().chat.completions.create(
                model=settings.OPENAI_CHAT_MODEL or settings.OPENAI_MODEL,
                max_completion_tokens=2500,
                temperature=0.2,
                messages=messages,
                tools=tools,
            )
        except openai.RateLimitError as exc:
            raise AIError("ИИ сейчас перегружен — попробуйте через минуту.") from exc
        except openai.AuthenticationError as exc:
            raise AIError("Ключ ИИ не подошёл — проверьте OPENAI_API_KEY.") from exc
        except openai.APIStatusError as exc:
            logger.error("OpenAI chat error %s: %s", exc.status_code, exc)
            raise AIError("ИИ временно недоступен.") from exc
        except openai.APIConnectionError as exc:
            raise AIError("Нет связи с ИИ — проверьте интернет.") from exc

        message = response.choices[0].message
        if getattr(message, "refusal", None):
            raise AIError("ИИ не стал отвечать на этот вопрос.")
        calls = message.tool_calls or []
        if not calls:
            return message.content or ""
        messages.append(
            {
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.function.name, "arguments": c.function.arguments},
                    }
                    for c in calls
                ],
            }
        )
        for call in calls:
            used.append(call.function.name)
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": run_tool(viewer, call.function.name, args),
                }
            )
    raise _too_long()
