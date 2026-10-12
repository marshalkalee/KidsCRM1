"""
Отток (TRU-127, ТЗ раздел 7): дети, которые ушли, — списком с контактами,
чтобы позвонить, а не только посчитать. Обратная сторона конверсии
продлений (TRU-126).

Что считаем уходом. Ребёнок ходит, пока у него идёт абонемент (любой
статус, любое направление, любой филиал). Ушёл — нет активного абонемента
дольше N дней после окончания последнего; N — настройка организации
`churn_inactive_days` (по умолчанию 30). Ребёнок, переведённый в статус
«ушёл», ушёл сразу после окончания абонемента, не дожидаясь N дней.
Пока N дней не прошло, ребёнок ещё не ушёл: он в риск-листе (TRU-122),
его можно удержать. Здесь его нет — разные списки, разные действия.

Сезонность. Летом в детском центре уходят почти все, в сентябре половина
возвращается: в лоб июнь показал бы катастрофу, которой нет. Поэтому
(настройка `churn_summer_pause`, по умолчанию включена): если N дней после
окончания абонемента задевают лето (1 июня — 31 августа), ребёнок до
30 сентября на «паузе на лето», а не ушёл. Вернулся до 30 сентября — не
уходил вовсе, срок жизни идёт дальше. Не вернулся — ушёл, датой окончания
последнего абонемента (честный июнь, но только из тех, кто не вернулся).
Поэтому летние месяцы окончательны только с 1 октября, а каждый месяц
сравниваем с тем же месяцем прошлого года, а не с предыдущим.

Срок жизни клиента — от начала первого абонемента до окончания последнего
без перерыва дольше порога (летняя пауза перерывом не считается). История
— с первого абонемента в системе: у перенесённых из старой базы срок
короче настоящего.

Причина ухода — поле карточки ребёнка (ТЗ п. 3.1), заполняется при
переводе в «ушёл». Ушедшие по правилу, но не переведённые в «ушёл», идут
с пометкой «не отмечен ушедшим»: их стоит отметить и спросить причину.

Даты ухода в карточке нет — дата ухода здесь это окончание последнего
абонемента. Без абонементов (только пробное) — не клиент, в отток не идёт.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median

from domains.money.subscriptions.models import Subscription
from domains.money.subscriptions.renewal_conversion import (
    RenewalIndex,
    add_months,
    grace_days,
    in_branches,
    load_rows,
)
from domains.people.clients.models import Child
from domains.platform.core.utils import today_for_org
from domains.platform.tenants.org_settings import (
    CHURN_INACTIVE_DAYS,
    CHURN_SUMMER_PAUSE,
    get_org_setting,
)
from domains.platform.users.models import User

from .contacts import parent_contacts
from .renewal_report import _context, _group_of, _groups_context

# Лето — с 1 июня по 31 августа, вернуться можно до 30 сентября.
SUMMER_START = (6, 1)
SUMMER_END = (8, 31)
RETURN_BY = (9, 30)
TREND_MONTHS = 12
DAYS_IN_MONTH = 30.44
EARLIEST = date(2000, 1, 1)
NOT_SET = "Не указано"
NO_REASON = "Причина не указана"
NOT_MARKED = "Не отмечен ушедшим"

# Сколько прожил клиент до ухода, месяцев.
LIFETIME_BUCKETS = [
    ("under_3", "До 3 месяцев", 0, 3),
    ("3_6", "3–6 месяцев", 3, 6),
    ("6_12", "6–12 месяцев", 6, 12),
    ("12_24", "1–2 года", 12, 24),
    ("over_24", "Больше 2 лет", 24, None),
]

DIMENSIONS = [
    ("branch", "Филиал"),
    ("direction", "Направление"),
    ("group", "Группа"),
    ("teacher", "Преподаватель"),
    ("lifetime", "Срок жизни"),
    ("reason", "Причина ухода"),
]

ACTIVE = "active"
RECENT = "recent"  # абонемент кончился меньше N дней назад — риск-лист
SUMMER = "summer"  # пауза на лето, ждём до 30 сентября
DEPARTED = "departed"


@dataclass(frozen=True)
class ChurnRules:
    inactive_days: int
    summer_pause: bool

    def deadline(self, end: date) -> date:
        """Последний день, когда новый абонемент ещё не делает перерыв уходом."""
        base = end + timedelta(days=self.inactive_days)
        if self.summer_pause:
            summer_start = date(end.year, *SUMMER_START)
            summer_end = date(end.year, *SUMMER_END)
            if end <= summer_end and base >= summer_start:
                return max(base, date(end.year, *RETURN_BY))
        return base

    def as_dict(self):
        return {
            "inactive_days": self.inactive_days,
            "summer_pause": self.summer_pause,
            "summer": "06-01..08-31",
            "return_by": "09-30",
        }


def churn_rules(organization) -> ChurnRules:
    return ChurnRules(
        int(get_org_setting(organization, CHURN_INACTIVE_DAYS)),
        bool(get_org_setting(organization, CHURN_SUMMER_PAUSE)),
    )


@dataclass
class Spell:
    """Непрерывное время клиента: абонементы без перерыва дольше порога."""

    child_id: object
    rows: list = field(default_factory=list)
    summer_returns: list = field(default_factory=list)  # окончания перед летней паузой

    @property
    def start(self) -> date:
        return self.rows[0].starts_on

    @property
    def end(self) -> date:
        return max(row.ends_on for row in self.rows)

    @property
    def last(self):
        """Абонемент, которым закончилось время клиента: филиал, направление."""
        return max(self.rows, key=lambda row: (row.ends_on, row.starts_on, row.created_on))

    @property
    def lifetime_days(self) -> int:
        return (self.end - self.start).days + 1


def build_spells(rows, rules: ChurnRules) -> dict:
    """{child_id: [Spell, …]} по возрастанию начала."""
    by_child = defaultdict(list)
    for row in rows:
        by_child[row.child_id].append(row)
    result = {}
    for child_id, child_rows in by_child.items():
        spells = []
        for row in sorted(child_rows, key=lambda r: (r.starts_on, r.ends_on)):
            if spells:
                current = spells[-1]
                end = current.end
                if row.starts_on <= rules.deadline(end):
                    if row.starts_on > end + timedelta(days=rules.inactive_days):
                        current.summer_returns.append(end)
                    current.rows.append(row)
                    continue
            spells.append(Spell(child_id, [row]))
        result[child_id] = spells
    return result


def _state(spell, is_last, marked_left, rules, today):
    if spell.end >= today:
        return ACTIVE
    if not is_last or today > rules.deadline(spell.end):
        return DEPARTED
    # Отмечен «ушёл» — ушёл сразу, порог ждать незачем.
    if marked_left:
        return DEPARTED
    if today <= spell.end + timedelta(days=rules.inactive_days):
        return RECENT
    return SUMMER


def _load(organization, child_ids=None):
    rules = churn_rules(organization)
    rows = load_rows(organization, ends_since=EARLIEST, child_ids=child_ids)
    spells = build_spells(rows, rules)
    left = set(
        Child.objects.for_tenant(organization)
        .filter(pk__in=spells.keys(), status=Child.Status.LEFT)
        .values_list("pk", flat=True)
    )
    return rules, rows, spells, left


def departed_child_ids(organization, child_ids, today=None) -> set:
    """Кто из этих детей уже ушёл и не вернулся — для риск-листа: он про
    тех, кого ещё можно удержать, ушедшие — здесь."""
    if not child_ids:
        return set()
    today = today or today_for_org(organization)
    rules, _rows, spells, left = _load(organization, child_ids)
    return {
        child_id
        for child_id, child_spells in spells.items()
        if _state(child_spells[-1], True, child_id in left, rules, today) == DEPARTED
    }


@dataclass
class Event:
    """Уход: время клиента закончилось и не продолжилось в срок."""

    spell: Spell
    returned_on: date | None
    marked_left: bool


def _events(spells, left, rules, today):
    """Все уходы (в том числе вернувшихся потом) и ожидающие: летняя пауза и
    «ещё в риск-листе» — последние отдельно, в отток не идут."""
    departed, waiting = [], []
    for child_id, child_spells in spells.items():
        for position, spell in enumerate(child_spells):
            is_last = position == len(child_spells) - 1
            state = _state(spell, is_last, child_id in left, rules, today)
            if state == DEPARTED:
                returned = None if is_last else child_spells[position + 1].start
                departed.append(Event(spell, returned, is_last and child_id in left))
            elif state in (RECENT, SUMMER):
                waiting.append((state, spell))
    return departed, waiting


def _in_scope(row, branch_ids):
    return in_branches(row, branch_ids)


def _active_children(rows, start, end, branch_ids):
    """Дети, у которых шёл абонемент хоть день периода, — база для доли ушедших."""
    return {
        row.child_id
        for row in rows
        if row.starts_on <= end and row.ends_on >= start and _in_scope(row, branch_ids)
    }


def _left_in(events, start, end, branch_ids):
    return [
        event
        for event in events
        if start <= event.spell.end <= end and _in_scope(event.spell.last, branch_ids)
    ]


def _rate(part, whole):
    return round(part * 100 / whole, 1) if whole else None


def _months(days):
    return round(days / DAYS_IN_MONTH, 1)


def _lifetime_bucket(days):
    months = days / DAYS_IN_MONTH
    for key, _label, low, high in LIFETIME_BUCKETS:
        if months >= low and (high is None or months < high):
            return key
    return LIFETIME_BUCKETS[-1][0]


def _lifetime(events):
    days = [event.spell.lifetime_days for event in events]
    counts = defaultdict(int)
    for value in days:
        counts[_lifetime_bucket(value)] += 1
    return {
        "departed": len(days),
        "average_months": _months(sum(days) / len(days)) if days else None,
        "median_months": _months(median(days)) if days else None,
        "buckets": [
            {
                "key": key,
                "label": label,
                "value": counts[key],
                "share": _rate(counts[key], len(days)),
            }
            for key, label, _low, _high in LIFETIME_BUCKETS
        ],
    }


def _month_stats(rows, events, waiting, month, branch_ids, rules, today):
    month_end = add_months(month, 1) - timedelta(days=1)
    left = _left_in(events, month, month_end, branch_ids)
    base = _active_children(rows, month, month_end, branch_ids)
    summer = sum(
        1
        for state, spell in waiting
        if state == SUMMER and month <= spell.end <= month_end and _in_scope(spell.last, branch_ids)
    )
    return {
        "month": month.isoformat(),
        "departed": len(left),
        "active": len(base),
        "rate": _rate(len(left), len(base)),
        "summer_waiting": summer,
        # Пока порог (или летняя пауза) для конца месяца не прошёл, цифра растёт.
        "complete": rules.deadline(month_end) < today,
    }


def _trend(rows, events, waiting, last_month, branch_ids, rules, today):
    result = []
    for offset in range(TREND_MONTHS):
        month = add_months(last_month, offset - (TREND_MONTHS - 1))
        current = _month_stats(rows, events, waiting, month, branch_ids, rules, today)
        previous = _month_stats(
            rows, events, waiting, add_months(month, -12), branch_ids, rules, today
        )
        current["previous_year"] = {
            "month": previous["month"],
            "departed": previous["departed"],
            "active": previous["active"],
            "rate": previous["rate"],
        }
        result.append(current)
    return result


# ── подписи и разрезы ───────────────────────────────────────────────────────


def _details(organization, rows):
    values = (
        Subscription.objects.for_tenant(organization)
        .filter(pk__in=[row.id for row in rows])
        .values(
            "id",
            "branch__name",
            "direction__name",
            "subscription_type_version__subscription_type__name",
        )
    )
    return {item["id"]: item for item in values}


def _reason_key(text):
    return " ".join(text.split()).casefold()


def _items(organization, events):
    """Строки списка ушедших: ребёнок, когда ушёл, сколько прожил, где
    ходил, причина и контакт родителя."""
    lasts = [event.spell.last for event in events]
    details = _details(organization, lasts)
    group_of = _group_of(organization, lasts)
    groups = _groups_context(organization, set(group_of.values()))
    teacher_names = dict(
        User.objects.filter(
            organization=organization,
            pk__in={pk for group in groups.values() for pk in group["teacher_ids"]},
        ).values_list("id", "full_name")
    )
    child_ids = {event.spell.child_id for event in events}
    children = {
        child.id: child
        for child in Child.objects.for_tenant(organization)
        .filter(pk__in=child_ids)
        .only("id", "full_name", "status", "leave_reason")
    }
    contacts = parent_contacts(organization, child_ids)

    items = []
    for event in events:
        spell, last = event.spell, event.spell.last
        child = children.get(spell.child_id)
        if child is None:  # удалённый ребёнок — абонементы остались
            continue
        detail = details.get(last.id, {})
        group = groups.get(group_of.get(last.id))
        reason = child.leave_reason.strip() if event.marked_left else ""
        items.append(
            {
                "id": str(child.id),
                "name": child.full_name,
                "status": child.status,
                "marked_left": event.marked_left,
                "reason": reason,
                "left_on": spell.end.isoformat(),
                "started_on": spell.start.isoformat(),
                "lifetime_days": spell.lifetime_days,
                "lifetime_months": _months(spell.lifetime_days),
                "lifetime_bucket": _lifetime_bucket(spell.lifetime_days),
                "returned_on": event.returned_on.isoformat() if event.returned_on else None,
                "summer_pauses": len(spell.summer_returns),
                "branch_id": str(last.branch_id) if last.branch_id else None,
                "branch": detail.get("branch__name"),
                "direction_id": str(last.direction_id) if last.direction_id else None,
                "direction": detail.get("direction__name"),
                "subscription": detail.get("subscription_type_version__subscription_type__name"),
                "group_id": group["id"] if group else None,
                "group": group["name"] if group else None,
                "teachers": [
                    {"id": str(pk), "name": teacher_names.get(pk, NOT_SET)}
                    for pk in (group["teacher_ids"] if group else [])
                ],
                "parent": None,
                "phone": None,
                "whatsapp": None,
                **contacts.get(child.id, {}),
            }
        )
    # Сначала не вернувшиеся, свежие уходы сверху: им звонить.
    items.sort(key=lambda row: row["left_on"], reverse=True)
    items.sort(key=lambda row: row["returned_on"] is not None)
    return items, groups


class _Counter:
    def __init__(self):
        self.departed = self.returned = self.lifetime_days = 0

    def add(self, item):
        self.departed += 1
        self.returned += item["returned_on"] is not None
        self.lifetime_days += item["lifetime_days"]

    def as_dict(self, total):
        return {
            "departed": self.departed,
            "returned": self.returned,
            "share": _rate(self.departed, total),
            "average_lifetime_months": (
                _months(self.lifetime_days / self.departed) if self.departed else None
            ),
        }


def _breakdowns(items, groups):
    counters = {key: defaultdict(_Counter) for key, _title in DIMENSIONS}
    labels = {key: {} for key, _title in DIMENSIONS}
    lifetime_labels = {key: label for key, label, _low, _high in LIFETIME_BUCKETS}
    for item in items:
        if not item["marked_left"]:
            reason = (None, NOT_MARKED)
        elif item["reason"]:
            reason = (_reason_key(item["reason"]), item["reason"])
        else:
            reason = ("", NO_REASON)
        keys = {
            "branch": [(item["branch_id"], item["branch"] or NOT_SET)],
            "direction": [(item["direction_id"], item["direction"] or NOT_SET)],
            "group": [(item["group_id"], item["group"] or "Без группы")],
            "teacher": (
                [(teacher["id"], teacher["name"]) for teacher in item["teachers"]]
                or [(None, "Без преподавателя")]
            ),
            "lifetime": [(item["lifetime_bucket"], lifetime_labels[item["lifetime_bucket"]])],
            "reason": [reason],
        }
        for dimension, pairs in keys.items():
            for key, label in pairs:
                counters[dimension][key].add(item)
                labels[dimension].setdefault(key, label)

    total = len(items)
    result = {
        dimension: [
            {"key": key, "label": labels[dimension][key], **counter.as_dict(total)}
            for key, counter in counters[dimension].items()
        ]
        for dimension, _title in DIMENSIONS
    }
    teacher_groups = defaultdict(list)
    for group in groups.values():
        for pk in group["teacher_ids"]:
            teacher_groups[str(pk)].append(group)
    groups_by_key = {group["id"]: group for group in groups.values()}
    for row in result["group"]:
        group = groups_by_key.get(row["key"])
        row["context"] = _context([group] if group else [])
    for row in result["teacher"]:
        row["context"] = _context(teacher_groups.get(row["key"], []))

    for dimension in ("branch", "direction", "group", "reason"):
        result[dimension].sort(key=lambda r: (r["key"] is None, -r["departed"], r["label"]))
    # Преподаватели — по алфавиту: это не рейтинг.
    result["teacher"].sort(key=lambda r: (r["key"] is None, r["label"]))
    order = [key for key, *_rest in LIFETIME_BUCKETS]
    result["lifetime"].sort(key=lambda r: order.index(r["key"]))
    return result


def _not_renewed(organization, rows, spells, left, rules, period, branch_ids, today):
    """Непродлившиеся: абонемент закончился в периоде, окно продления прошло,
    продления нет (то же определение, что в отчёте «Продления»). Рядом —
    ушёл ли ребёнок совсем или ходит дальше (другое направление)."""
    index = RenewalIndex(rows, grace_days(organization))
    known_before = today + timedelta(days=1)
    lost = [
        row
        for row in index.rows
        if period.start <= row.ends_on <= period.end
        and _in_scope(row, branch_ids)
        and row.ends_on + timedelta(days=index.grace_days) < today
        and index.renewal_of(row, known_before) is None
    ]
    state_of = {}
    for child_id, child_spells in spells.items():
        for position, spell in enumerate(child_spells):
            is_last = position == len(child_spells) - 1
            state = _state(spell, is_last, child_id in left, rules, today)
            for row in spell.rows:
                state_of[row.id] = state
    details = _details(organization, lost)
    children = dict(
        Child.objects.for_tenant(organization)
        .filter(pk__in={row.child_id for row in lost})
        .values_list("id", "full_name")
    )
    contacts = parent_contacts(organization, children.keys())
    items = []
    for row in lost:
        if row.child_id not in children:
            continue
        detail = details.get(row.id, {})
        items.append(
            {
                "id": str(row.id),
                "child_id": str(row.child_id),
                "name": children[row.child_id],
                "ends_on": row.ends_on.isoformat(),
                "branch": detail.get("branch__name"),
                "direction": detail.get("direction__name"),
                "subscription": detail.get("subscription_type_version__subscription_type__name"),
                # active — ходит дальше (другое направление); departed — ушёл
                # совсем; summer — пауза на лето; recent — в риск-листе.
                "child_state": state_of.get(row.id, DEPARTED),
                "parent": None,
                "phone": None,
                "whatsapp": None,
                **contacts.get(row.child_id, {}),
            }
        )
    items.sort(key=lambda item: (item["ends_on"], item["name"]), reverse=True)
    return items


def churn_report(scope, period) -> dict:
    organization = scope.organization
    today = today_for_org(organization)
    branch_ids = scope.branch_ids
    rules, rows, spells, left = _load(organization)
    events, waiting = _events(spells, left, rules, today)

    in_period = _left_in(events, period.start, period.end, branch_ids)
    items, groups = _items(organization, in_period)
    base = _active_children(rows, period.start, period.end, branch_ids)

    def waiting_count(kind):
        return sum(
            1
            for state, spell in waiting
            if state == kind
            and period.start <= spell.end <= period.end
            and _in_scope(spell.last, branch_ids)
        )

    year_ago_start, year_ago_end = add_months(period.start, -12), add_months(period.end, -12)
    year_ago = _left_in(events, year_ago_start, year_ago_end, branch_ids)
    year_ago_base = _active_children(rows, year_ago_start, year_ago_end, branch_ids)
    summer_returned = sum(
        1
        for child_spells in spells.values()
        for spell in child_spells
        for end in spell.summer_returns
        if period.start <= end <= period.end and _in_scope(spell.last, branch_ids)
    )
    # Годовой срок жизни — устойчивее, чем за месяц: берём 12 месяцев до конца периода.
    year_start = add_months(period.end.replace(day=1), -(TREND_MONTHS - 1))

    return {
        "period": period.as_dict(),
        "today": today.isoformat(),
        "rules": {**rules.as_dict(), "grace_days": grace_days(organization)},
        "summary": {
            "departed": len(items),
            "returned": sum(item["returned_on"] is not None for item in items),
            "not_marked": sum(not item["marked_left"] for item in items),
            "active": len(base),
            "rate": _rate(len(items), len(base)),
            "summer_waiting": waiting_count(SUMMER),
            "summer_returned": summer_returned,
            "recent": waiting_count(RECENT),
            "previous_year": {
                "start": year_ago_start.isoformat(),
                "end": year_ago_end.isoformat(),
                "departed": len(year_ago),
                "active": len(year_ago_base),
                "rate": _rate(len(year_ago), len(year_ago_base)),
            },
            # Окончательно, когда порог (и летняя пауза) прошёл для конца периода.
            "complete": rules.deadline(period.end) < today,
        },
        "lifetime": {
            "period": _lifetime(in_period),
            "year": _lifetime(_left_in(events, year_start, period.end, branch_ids)),
            "year_start": year_start.isoformat(),
        },
        "trend": _trend(rows, events, waiting, period.end.replace(day=1), branch_ids, rules, today),
        "breakdowns": _breakdowns(items, groups),
        "items": items,
        "not_renewed": _not_renewed(
            organization, rows, spells, left, rules, period, branch_ids, today
        ),
    }
