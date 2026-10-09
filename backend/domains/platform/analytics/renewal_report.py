"""
Конверсия продлений (TRU-126, ТЗ п. 5.3): сколько абонементов продлено из
числа закончившихся за период.

Что такое «продлён» — одно определение с прогнозом выручки:
money/subscriptions/renewal_conversion.py (окно — настройка организации
`renewal_grace_days`). Здесь только разрезы поверх него.

Как считаем, чтобы цифра совпала с ручным подсчётом за месяц:
- «Закончился в периоде» — дата окончания абонемента в периоде, любой
  статус (истёк, исчерпан, ещё активен в последний день). Филиал — филиал
  абонемента.
- Продление ищем по всем продажам на сегодня, в любом филиале.
- Конверсия = продлённые / закончившиеся, у которых окно продления уже
  прошло. Пока окно идёт, «не продлил» записывать рано, а ранние продления
  без поздних завысили бы процент: такие абонементы показываем отдельно
  («окно идёт», из них уже продлили), в конверсию не берём. За прошлый
  месяц окно обычно уже прошло — ручной подсчёт совпадает целиком.
- Первое продление (абонемент был первым у ребёнка в направлении) и
  последующие — отдельно: первое всегда труднее.
- Срок продления — день покупки продления относительно окончания.

Разрез по преподавателю — не рейтинг: строки по алфавиту, рядом
заполняемость и время занятий его групп (низкая конверсия может быть из-за
неудобного времени или возраста детей). Группа абонемента — группа того же
направления, в которой ребёнок был, пока шёл абонемент; преподаватели —
текущие преподаватели группы (истории преподавателей нет).
"""

from collections import defaultdict
from datetime import timedelta

from django.db.models import Min, Prefetch

from domains.money.subscriptions.models import Subscription
from domains.money.subscriptions.renewal_conversion import (
    RenewalIndex,
    add_months,
    grace_days,
    in_branches,
    load_rows,
)
from domains.platform.core.utils import today_for_org
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.groups.queries import active_template, fill_percent, with_members_count
from domains.scheduling.schedule_templates.models import ScheduleTemplate

# Меньше решённых абонементов в строке разреза — процент ненадёжен:
# показываем, но с пометкой «мало данных».
MIN_SAMPLE = 10
TREND_MONTHS = 12
NO_GROUP = "Без группы"
NOT_SET = "Не указано"
WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

# Срок продления: на какой день после окончания купили продление.
GAP_BUCKETS = [
    ("early", "Заранее или в день окончания", None, 0),
    ("week", "1–7 дней", 1, 7),
    ("two_weeks", "8–14 дней", 8, 14),
    ("month", "15–30 дней", 15, 30),
    ("later", "Больше 30 дней", 31, None),
]
# Пауза дольше недели — риск потери (ребёнок отвыкает ходить).
LONG_GAP_DAYS = 7

DIMENSIONS = [
    ("branch", "Филиал"),
    ("direction", "Направление"),
    ("group", "Группа"),
    ("teacher", "Преподаватель"),
    ("type", "Тип абонемента"),
    ("age", "Возраст ребёнка"),
]


def _rate(renewed, decided):
    return round(renewed * 100 / decided, 1) if decided else None


class _Counter:
    """Закончилось / окно прошло / продлили — всего и отдельно для первых."""

    def __init__(self):
        self.ended = self.pending = self.pending_renewed = 0
        self.decided = {"all": 0, "first": 0, "repeat": 0}
        self.renewed = {"all": 0, "first": 0, "repeat": 0}

    def add(self, item):
        self.ended += 1
        if not item["decided"]:
            self.pending += 1
            self.pending_renewed += item["renewed"]
            return
        for kind in ("all", "first" if item["first"] else "repeat"):
            self.decided[kind] += 1
            self.renewed[kind] += item["renewed"]

    def as_dict(self):
        def part(kind):
            decided, renewed = self.decided[kind], self.renewed[kind]
            return {"decided": decided, "renewed": renewed, "rate": _rate(renewed, decided)}

        return {
            "ended": self.ended,
            "decided": self.decided["all"],
            "renewed": self.renewed["all"],
            "lost": self.decided["all"] - self.renewed["all"],
            "rate": _rate(self.renewed["all"], self.decided["all"]),
            "pending": self.pending,
            "pending_renewed": self.pending_renewed,
            "first": part("first"),
            "repeat": part("repeat"),
            "small": self.decided["all"] < MIN_SAMPLE,
        }


def _gap_bucket(days):
    for key, _label, low, high in GAP_BUCKETS:
        if (low is None or days >= low) and (high is None or days <= high):
            return key
    return GAP_BUCKETS[-1][0]


def _age(birth_date, day):
    if birth_date is None:
        return None
    years = day.year - birth_date.year
    if (day.month, day.day) < (birth_date.month, birth_date.day):
        years -= 1
    return max(years, 0)


def _age_label(years):
    if years % 10 == 1 and years % 100 != 11:
        word = "год"
    elif years % 10 in (2, 3, 4) and years % 100 not in (12, 13, 14):
        word = "года"
    else:
        word = "лет"
    return f"{years} {word}"


def _load_index(organization, start, today):
    """Абонементы, нужные отчёту: закончившиеся с начала динамики и всё
    после них (продления), плюс те, что могли быть их предшественниками —
    иначе первый абонемент не отличить от продления."""
    grace = grace_days(organization)
    trend_start = min(start, add_months(today.replace(day=1), -(TREND_MONTHS - 1)))
    earliest = (
        Subscription.objects.for_tenant(organization)
        .filter(ends_on__gte=trend_start)
        .aggregate(first=Min("starts_on"))["first"]
    )
    since = min(trend_start, earliest or trend_start) - timedelta(days=grace + 1)
    return RenewalIndex(load_rows(organization, ends_since=since), grace)


def _classify(index, rows, today):
    known_before = today + timedelta(days=1)
    items = []
    for row in rows:
        renewal = index.renewal_of(row, known_before)
        # Решено — только когда окно прошло у всех: иначе ранние продления
        # попадали бы в процент раньше поздних и завышали его.
        decided = row.ends_on + timedelta(days=index.grace_days) < today
        items.append(
            {
                "row": row,
                "renewed": renewal is not None,
                "renewal": renewal,
                "decided": decided,
                "first": index.is_first(row),
            }
        )
    return items


def _ended_rows(index, start, end, branch_ids):
    return [
        row for row in index.rows if start <= row.ends_on <= end and in_branches(row, branch_ids)
    ]


# ── группы и преподаватели ──────────────────────────────────────────────────


def _groups_context(organization, group_ids):
    """Группа → заполняемость сейчас, расписание, преподаватели: контекст
    для разрезов по группе и преподавателю."""
    templates = ScheduleTemplate.objects.prefetch_related("slots").order_by("-valid_from")
    groups = with_members_count(
        Group.objects.for_tenant(organization)
        .filter(pk__in=group_ids)
        .prefetch_related("teachers", Prefetch("schedule_templates", queryset=templates))
    )
    context = {}
    for group in groups:
        template = active_template(group)
        slots = (
            sorted(template.slots.all(), key=lambda s: (s.weekday, s.start_time))
            if template
            else []
        )
        teacher_ids = [teacher.id for teacher in group.teachers.all()]
        for slot in slots:
            if slot.teacher_id and slot.teacher_id not in teacher_ids:
                teacher_ids.append(slot.teacher_id)
        context[group.id] = {
            "id": str(group.id),
            "name": group.name,
            "occupied": group.members_count,
            "capacity": group.capacity,
            "fill_percent": fill_percent(group),
            "slots": [
                {"weekday": slot.weekday, "time": slot.start_time.strftime("%H:%M")}
                for slot in slots
            ],
            "schedule": ", ".join(
                f"{WEEKDAYS[slot.weekday]} {slot.start_time.strftime('%H:%M')}" for slot in slots
            ),
            "teacher_ids": teacher_ids,
        }
    return context


def _group_of(organization, rows):
    """Абонемент → группа того же направления, в которой ребёнок был, пока
    шёл абонемент (последняя по дате вступления; при равенстве — в филиале
    абонемента)."""
    child_ids = {row.child_id for row in rows}
    memberships = defaultdict(list)
    for membership in (
        GroupMembership.objects.for_tenant(organization)
        .filter(child_id__in=child_ids)
        .values(
            "child_id",
            "group_id",
            "group__direction_id",
            "group__branch_id",
            "joined_at",
            "left_at",
        )
    ):
        memberships[membership["child_id"]].append(membership)
    result = {}
    for row in rows:
        candidates = [
            m
            for m in memberships[row.child_id]
            if m["group__direction_id"] == row.direction_id
            and m["joined_at"] <= row.ends_on
            and (m["left_at"] is None or m["left_at"] >= row.starts_on)
        ]
        if candidates:
            best = max(
                candidates,
                key=lambda m: (m["group__branch_id"] == row.branch_id, m["joined_at"]),
            )
            result[row.id] = best["group_id"]
    return result


# ── отчёт ───────────────────────────────────────────────────────────────────


def _details(organization, rows):
    """Подписи, которых нет в строках расчёта: тип абонемента, дата рождения,
    названия филиалов и направлений."""
    values = (
        Subscription.objects.for_tenant(organization)
        .filter(pk__in=[row.id for row in rows])
        .values(
            "id",
            "branch__name",
            "direction__name",
            "subscription_type_version__subscription_type_id",
            "subscription_type_version__subscription_type__name",
            "child__birth_date",
        )
    )
    return {item["id"]: item for item in values}


def _breakdowns(organization, items):
    rows = [item["row"] for item in items]
    details = _details(organization, rows)
    group_of = _group_of(organization, rows)
    groups = _groups_context(organization, set(group_of.values()))
    teacher_names = dict(
        User.objects.filter(
            organization=organization,
            pk__in={pk for group in groups.values() for pk in group["teacher_ids"]},
        ).values_list("id", "full_name")
    )

    counters = {key: defaultdict(_Counter) for key, _title in DIMENSIONS}
    labels = {key: {} for key, _title in DIMENSIONS}
    for item in items:
        row, detail = item["row"], details.get(item["row"].id, {})
        keys = {
            "branch": [(row.branch_id, detail.get("branch__name") or NOT_SET)],
            "direction": [(row.direction_id, detail.get("direction__name") or NOT_SET)],
            "type": [
                (
                    detail.get("subscription_type_version__subscription_type_id"),
                    detail.get("subscription_type_version__subscription_type__name") or NOT_SET,
                )
            ],
        }
        age = _age(detail.get("child__birth_date"), row.ends_on)
        keys["age"] = [(age, NOT_SET if age is None else _age_label(age))]
        group = groups.get(group_of.get(row.id))
        keys["group"] = [(group["id"], group["name"]) if group else (None, NO_GROUP)]
        keys["teacher"] = (
            [(str(pk), teacher_names.get(pk, NOT_SET)) for pk in group["teacher_ids"]]
            if group and group["teacher_ids"]
            else [(None, "Без преподавателя")]
        )
        for dimension, pairs in keys.items():
            for key, label in pairs:
                counters[dimension][key].add(item)
                labels[dimension][key] = label

    result = {}
    for dimension, _title in DIMENSIONS:
        result[dimension] = [
            {
                "key": None if key is None else str(key),
                "label": labels[dimension][key],
                **counter.as_dict(),
            }
            for key, counter in counters[dimension].items()
        ]

    # Контекст преподавателя и группы: заполняемость и время занятий.
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

    for dimension in ("branch", "direction", "group", "type"):
        result[dimension].sort(key=lambda r: (r["key"] is None, -r["ended"], r["label"]))
    # Преподаватели — по алфавиту, не по конверсии: это не рейтинг.
    result["teacher"].sort(key=lambda r: (r["key"] is None, r["label"]))
    result["age"].sort(key=lambda r: (r["key"] is None, int(r["key"] or 0)))
    return result


def _context(groups):
    occupied = sum(group["occupied"] for group in groups)
    capacity = sum(group["capacity"] or 0 for group in groups)
    return {
        "fill_percent": round(occupied * 100 / capacity) if capacity else None,
        "groups": [
            {
                "name": group["name"],
                "fill_percent": group["fill_percent"],
                "occupied": group["occupied"],
                "capacity": group["capacity"],
                "schedule": group["schedule"],
                "slots": group["slots"],
            }
            for group in sorted(groups, key=lambda g: g["name"])
        ],
    }


def _gaps(items):
    """Через сколько дней после окончания купили продление."""
    counts = defaultdict(int)
    days = []
    for item in items:
        if not item["renewed"]:
            continue
        gap = (item["renewal"].created_on - item["row"].ends_on).days
        days.append(max(gap, 0))
        counts[_gap_bucket(gap)] += 1
    total = len(days)
    return {
        "buckets": [
            {
                "key": key,
                "label": label,
                "value": counts[key],
                "share": round(counts[key] * 100 / total, 1) if total else None,
            }
            for key, label, _low, _high in GAP_BUCKETS
        ],
        "renewed": total,
        "average_days": round(sum(days) / total, 1) if total else None,
        "long_pause": sum(1 for gap in days if gap > LONG_GAP_DAYS),
        "long_pause_days": LONG_GAP_DAYS,
    }


def _trend(index, items_by_month, today):
    result = []
    for month, items in items_by_month:
        counter = _Counter()
        for item in items:
            counter.add(item)
        month_end = add_months(month, 1) - timedelta(days=1)
        result.append(
            {
                "month": month.isoformat(),
                **counter.as_dict(),
                # Окно продления для конца месяца ещё идёт — цифра дособирается.
                "complete": month_end + timedelta(days=index.grace_days) < today,
            }
        )
    return result


def renewal_conversion_report(scope, period) -> dict:
    organization = scope.organization
    today = today_for_org(organization)
    index = _load_index(organization, period.start, today)
    branch_ids = scope.branch_ids

    items = _classify(index, _ended_rows(index, period.start, period.end, branch_ids), today)
    summary = _Counter()
    for item in items:
        summary.add(item)

    # Динамика — 12 месяцев, последний — месяц конца периода.
    last_month = period.end.replace(day=1)
    months = [add_months(last_month, offset - (TREND_MONTHS - 1)) for offset in range(TREND_MONTHS)]
    by_month = []
    for month in months:
        month_end = min(add_months(month, 1) - timedelta(days=1), today)
        by_month.append(
            (month, _classify(index, _ended_rows(index, month, month_end, branch_ids), today))
        )

    return {
        "period": period.as_dict(),
        "today": today.isoformat(),
        "rules": {
            "grace_days": index.grace_days,
            "min_sample": MIN_SAMPLE,
            "long_pause_days": LONG_GAP_DAYS,
        },
        "summary": summary.as_dict(),
        "trend": _trend(index, by_month, today),
        "gaps": _gaps(items),
        "breakdowns": _breakdowns(organization, items),
    }
