"""
Отчёты для выгрузки в Excel (TRU-114): что лежит в каждом отчёте — те же
метрики, разбивки и воронка, что на экране. Новый отчёт M3 — функция с
@report здесь и кнопка `<ExportButton report="…" />` на его странице.
"""

from collections.abc import Callable
from dataclasses import dataclass

from .attendance_trends import attendance_trends
from .branches import COLUMNS as BRANCH_COLUMNS
from .branches import compare_branches
from .breakdowns import breakdown, visits_heatmap
from .export import Column, Export, Section
from .funnel import BY as FUNNEL_BY
from .funnel import STAGES, funnel, funnel_by
from .group_occupancy import group_occupancy
from .registry import REGISTRY, compute
from .rejections import STAGES as REJECTION_STAGES
from .rejections import rejection_comments, rejections, rejections_by
from .risk_list import risk_list
from .sources import SMALL_SAMPLE, sources_by_month, sources_quality
from .teacher_load import teacher_workload

UNIT_TITLE = {"money": ", ₸", "percent": ", %", "count": "", "decimal": ""}
WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
NOT_SET = "Не указано"


@dataclass(frozen=True)
class Report:
    name: str
    title: str
    build: Callable


REPORTS: dict[str, Report] = {}


def report(name, title):
    def wrap(build):
        REPORTS[name] = Report(name, title, build)
        return build

    return wrap


# ── общие таблицы ───────────────────────────────────────────────────────────


def metrics_section(names, scope, period):
    data = compute(names, scope, period, series=False)
    rows = []
    for name in names:
        metric = data[name]
        unit = metric["unit"]
        rows.append(
            [
                REGISTRY[name].label,
                (metric["value"], unit),
                (metric.get("previous"), unit),
                (metric.get("change_percent"), "percent"),
                "сейчас" if metric["kind"] == "snapshot" else "за период",
            ]
        )
    return Section(
        "Показатели",
        [
            Column("Показатель", width=28),
            Column("Значение", "decimal", 16, total=False),
            Column("Прошлый период", "decimal", 16, total=False),
            Column("Изменение, %", "percent", 14),
            Column("Смысл", width=12),
        ],
        rows,
        note="Деньги — в тенге, доли — в процентах.",
    )


def series_section(names, scope, period, *, previous_of=None, title="Динамика"):
    data = compute(names, scope, period)
    columns = [Column("Период с", "date", 14)]
    series = []
    for name in names:
        unit = data[name]["unit"]
        columns.append(Column(f"{REGISTRY[name].label}{UNIT_TITLE[unit]}", unit, 18))
        series.append([point["value"] for point in data[name]["series"]])
    if previous_of:
        unit = data[previous_of]["unit"]
        columns.append(
            Column(f"{REGISTRY[previous_of].label} — прошлый период{UNIT_TITLE[unit]}", unit, 22)
        )
        series.append([point["value"] for point in data[previous_of].get("previous_series", [])])
    dates = [point["date"] for point in data[names[0]]["series"]]
    rows = [
        [day, *[column[i] if i < len(column) else None for column in series]]
        for i, day in enumerate(dates)
    ]
    step = {"day": "по дням", "week": "по неделям", "month": "по месяцам"}[period.granularity]
    return Section(title, columns, rows, note=f"Шаг — {step}.")


def breakdown_section(title, label_title, metric, dimension, scope, period):
    items = breakdown(metric, dimension, scope, period)
    unit = REGISTRY[metric].unit
    total = sum(float(item["value"]) for item in items) or None
    rows = [
        [
            item["label"] or NOT_SET,
            item["value"],
            round(float(item["value"]) * 100 / total, 1) if total else None,
        ]
        for item in items
    ]
    return Section(
        title,
        [
            Column(label_title, width=28),
            Column(f"{REGISTRY[metric].label}{UNIT_TITLE[unit]}", unit, 18),
            Column("Доля, %", "percent", 10),
        ],
        rows,
    )


def rate_section(title, label_title, dimension, scope, period):
    visited = {i["key"]: float(i["value"]) for i in breakdown("visits", dimension, scope, period)}
    marks = breakdown("attendance_marks", dimension, scope, period)
    rows = []
    for item in marks:
        total = float(item["value"])
        came = visited.get(item["key"], 0)
        rows.append(
            [item["label"] or NOT_SET, total, came, round(came * 100 / total, 1) if total else None]
        )
    rows.sort(key=lambda row: (row[3] is None, row[3]))
    return Section(
        title,
        [
            Column(label_title, width=28),
            Column("Отметок", "count", 12),
            Column("Посещений", "count", 12),
            Column("Доля посещений, %", "percent", 18),
        ],
        rows,
    )


def heatmap_section(scope, period):
    cells = visits_heatmap(scope, period)
    hours = sorted({cell["hour"] for cell in cells})
    value = {(cell["weekday"], cell["hour"]): cell["value"] for cell in cells}
    rows = [
        [day, *[value.get((index + 1, hour), 0) for hour in hours]]
        for index, day in enumerate(WEEKDAYS)
    ]
    return Section(
        "Когда ходят",
        [Column("День", width=8), *[Column(f"{hour}:00", "count", 9) for hour in hours]],
        rows,
        note="Посещения по дню недели и часу начала занятия.",
    )


# ── отчёты ──────────────────────────────────────────────────────────────────

OVERVIEW = [
    "revenue",
    "payments_count",
    "average_check",
    "debt_total",
    "new_leads",
    "visits",
    "attendance_rate",
    "active_children",
    "group_fill",
]


@report("overview", "Аналитика — обзор")
def overview(scope, period, params):
    return [
        metrics_section(OVERVIEW, scope, period),
        series_section(["revenue", "visits", "attendance_rate", "new_leads"], scope, period),
        breakdown_section("Способы оплаты", "Способ оплаты", "revenue", "method", scope, period),
        breakdown_section("Выручка по филиалам", "Филиал", "revenue", "branch", scope, period),
        breakdown_section("Отметки", "Отметка", "attendance_marks", "status", scope, period),
        breakdown_section("Источники заявок", "Источник", "new_leads", "source", scope, period),
        heatmap_section(scope, period),
    ]


@report("revenue", "Выручка по оплатам")
def revenue(scope, period, params):
    sections = [
        metrics_section(
            ["revenue", "payments_count", "average_check", "debt_total"], scope, period
        ),
        series_section(["revenue", "payments_count"], scope, period, previous_of="revenue"),
    ]
    for title, label, dimension in [
        ("Новые и продления", "Клиенты", "client"),
        ("По филиалам", "Филиал", "branch"),
        ("По направлениям", "Направление", "direction"),
        ("По типам абонементов", "Тип абонемента", "subscription_type"),
        ("Способы оплаты", "Способ оплаты", "method"),
    ]:
        sections.append(breakdown_section(title, label, "revenue", dimension, scope, period))
    sections[0].note = (
        "Выручка — по дате оплаты: сколько денег пришло, а не сколько абонементов продано. "
        "Деньги — в тенге, доли — в процентах."
    )
    return sections


@report("attendance", "Посещаемость и пропуски")
def attendance(scope, period, params):
    data = attendance_trends(scope, period)
    summary = data["summary"]
    sections = [
        Section(
            "Сводка",
            [
                Column("Проведено занятий", "count", 18, total=False),
                Column("Отметок", "count", 12, total=False),
                Column("Посещений", "count", 12, total=False),
                Column("Пропусков", "count", 12, total=False),
                Column("Посещаемость, %", "percent", 18, total=False),
            ],
            [
                [
                    summary["lessons_held"],
                    summary["marked"],
                    summary["attended"],
                    summary["absences"],
                    summary["attendance_rate"],
                ]
            ],
        ),
        Section(
            "Динамика по неделям",
            [
                Column("Неделя с", "date", 14),
                Column("Проведено занятий", "count", 18),
                Column("Отметок", "count", 12),
                Column("Посещений", "count", 12),
                Column("Пропусков", "count", 12),
                Column("Посещаемость, %", "percent", 18, total=False),
            ],
            [
                [
                    row["date"],
                    row["lessons_held"],
                    row["marked"],
                    row["attended"],
                    row["absences"],
                    row["value"],
                ]
                for row in data["weekly"]
            ],
            note="Шаг всегда одна неделя: тренд важнее отдельного абсолютного числа.",
        ),
        Section(
            "Причины пропусков",
            [Column("Причина", width=28), Column("Пропусков", "count", 12)],
            [[row["label"] or NOT_SET, row["value"]] for row in data["absence_reasons"]],
        ),
    ]
    titles = {
        "group": ("По группам", "Группа"),
        "direction": ("По направлениям", "Направление"),
        "branch": ("По филиалам", "Филиал"),
        "teacher": ("По преподавателям", "Преподаватель"),
        "weekday": ("По дням недели", "День недели"),
    }
    for key, (title, label) in titles.items():
        sections.append(
            Section(
                title,
                [
                    Column(label, width=26),
                    Column("Проведено занятий", "count", 18),
                    Column("Отметок", "count", 12),
                    Column("Посещений", "count", 12),
                    Column("Пропусков", "count", 12),
                    Column("Посещаемость, %", "percent", 18, total=False),
                ],
                [
                    [
                        row["label"] or NOT_SET,
                        row["lessons_held"],
                        row["marked"],
                        row["attended"],
                        row["absences"],
                        row["value"],
                    ]
                    for row in data["breakdowns"][key]
                ],
            )
        )
    sections.append(
        Section(
            "По детям — отклонение от личной нормы",
            [
                Column("Ребёнок", width=28),
                Column("Отметок", "count", 12),
                Column("Посещений", "count", 12),
                Column("Пропусков", "count", 12),
                Column("Текущие пропуски, %", "percent", 20, total=False),
                Column("Личная норма, %", "percent", 18, total=False),
                Column("Отклонение, п.п.", "decimal", 18, total=False),
            ],
            [
                [
                    row["name"],
                    row["marked"],
                    row["attended"],
                    row["absences"],
                    row["absence_rate"],
                    row["baseline"]["absence_rate"] if row["has_baseline"] else None,
                    row["absence_change_pp"],
                ]
                for row in data["children"]
            ],
            note=(
                f"Личная норма — предыдущие {data['baseline']['days']} дней; "
                f"для сравнения нужно не меньше {data['baseline']['minimum_marks']} отметок. "
                "Отклонение доступно риск-листу, общий порог детям не назначается."
            ),
        )
    )
    return sections


FUNNEL_TITLES = {
    "source": "Источник",
    "direction": "Направление",
    "branch": "Филиал",
    "manager": "Ответственный",
}
STAGE_TITLES = {
    "new": "Заявки",
    "contacted": "Связались",
    "trial_scheduled": "Записаны на пробное",
    "trial_attended": "Пришли на пробное",
    "purchased": "Купили",
}


@report("funnel", "Воронка продаж")
def funnel_report(scope, period, params):
    filters = params.get("funnel_filters") or {}
    summary = funnel(scope, period, filters, compare=False)
    total = summary["total"]
    rows, previous = [], None
    for stage in summary["stages"]:
        count = stage["count"]
        rows.append(
            [
                STAGE_TITLES[stage["key"]],
                count,
                round(count * 100 / total, 1) if total else None,
                round(count * 100 / previous, 1) if previous else None,
                stage["current"],
            ]
        )
        previous = count
    stages = Section(
        "Воронка",
        [
            Column("Этап", width=24),
            Column("Заявок", "count", 12, total=False),
            Column("% от заявок", "percent", 14),
            Column("% от прошлого этапа", "percent", 18),
            Column("Сейчас на этапе", "count", 16, total=False),
        ],
        rows,
        note=(
            f"Новые заявки, созданные за период; продления не входят. Купили без пробного: "
            f"{summary['purchased_without_trial']}, думают: {summary['thinking']}, "
            f"отказались: {summary['rejected']}."
        ),
    )
    sections = [stages]
    for dimension in FUNNEL_BY:
        items = funnel_by(scope, period, dimension, filters)
        sections.append(
            Section(
                FUNNEL_TITLES[dimension],
                [
                    Column(FUNNEL_TITLES[dimension], width=26),
                    *[Column(STAGE_TITLES[stage], "count", 12) for stage in STAGES],
                    Column("Конверсия, %", "percent", 14),
                ],
                [
                    [
                        item["label"] or NOT_SET,
                        *[item["stages"][stage] for stage in STAGES],
                        item["conversion"],
                    ]
                    for item in items
                ],
            )
        )
    return sections


@report("group_occupancy", "Заполняемость групп")
def group_occupancy_report(scope, period, params):
    data = group_occupancy(scope, period, params.get("occupancy_filters"))
    summary = data["summary"]
    summary_section = Section(
        "Сводка",
        [
            Column("Групп", "count", 12, total=False),
            Column("Занято", "count", 12, total=False),
            Column("Вместимость", "count", 14, total=False),
            Column("Заполняемость, %", "percent", 18, total=False),
            Column("Недозаполнено", "count", 18, total=False),
            Column("Порог, %", "percent", 12, total=False),
        ],
        [
            [
                summary["groups_count"],
                summary["occupied"],
                summary["capacity"],
                summary["percent"],
                summary["underfilled_count"],
                data["threshold"],
            ]
        ],
    )
    groups = Section(
        "Группы",
        [
            Column("Группа", width=28),
            Column("Филиал", width=22),
            Column("Направление", width=22),
            Column("Занято", "count", 10),
            Column("Вместимость", "count", 14),
            Column("Заполняемость, %", "percent", 18, total=False),
            Column("Недозаполнена", width=16),
            Column("Рекомендация", width=24),
        ],
        [
            [
                row["name"],
                row["branch"],
                row["direction"],
                row["occupied"],
                row["capacity"],
                row["percent"],
                "Да" if row["is_underfilled"] else "Нет",
                "Рассмотреть объединение"
                if row["suggested_action"] == "merge"
                else "Продвигать набор",
            ]
            for row in data["groups"]
        ],
        note=f"Недозаполненной считается активная группа ниже {data['threshold']}%.",
    )
    trend = Section(
        "Динамика",
        [
            Column("Месяц", "date", 14),
            Column("Занято", "count", 12),
            Column("Вместимость", "count", 14),
            Column("Заполняемость, %", "percent", 18, total=False),
        ],
        [[row["date"], row["occupied"], row["capacity"], row["value"]] for row in data["trend"]],
        note="Состав на конец каждого месяца выбранного периода.",
    )
    sections = [summary_section, groups, trend]
    titles = {
        "branch": ("По филиалам", "Филиал"),
        "direction": ("По направлениям", "Направление"),
        "teacher": ("По преподавателям", "Преподаватель"),
        "weekday": ("По дням недели", "День недели"),
        "time": ("По времени", "Время"),
    }
    for key, (title, label) in titles.items():
        sections.append(
            Section(
                title,
                [
                    Column(label, width=24),
                    Column("Групп", "count", 10),
                    Column("Занято", "count", 10),
                    Column("Вместимость", "count", 14),
                    Column("Заполняемость, %", "percent", 18, total=False),
                ],
                [
                    [
                        row["label"],
                        row["groups_count"],
                        row["occupied"],
                        row["capacity"],
                        row["value"],
                    ]
                    for row in data["breakdowns"][key]
                ],
            )
        )
    return sections


@report("sources", "Источники заявок")
def sources_report(scope, period, params):
    filters = params.get("funnel_filters") or {}
    items = sources_quality(scope, period, filters)
    quality = Section(
        "Источники",
        [
            Column("Источник", width=24),
            Column("Заявок", "count", 10),
            Column("Пришли на пробное", "count", 14),
            Column("Купили", "count", 10),
            Column("До пробного, %", "percent", 14),
            Column("Конверсия в покупку, %", "percent", 16),
            Column("Средний чек, ₸", "money", 14, total=False),
            Column("Мало данных", width=12),
        ],
        [
            [
                item["label"] or NOT_SET,
                item["leads"],
                item["trial"],
                item["purchased"],
                item["trial_rate"],
                item["conversion"],
                item["avg_check"],
                "да" if item["small_sample"] else "",
            ]
            for item in items
        ],
        note=(
            f"Новые заявки, созданные за период. Меньше {SMALL_SAMPLE} заявок — выводы рано. "
            "Стоимость источника не считается: расходов на рекламу в системе нет. "
            "Средний чек — по абонементам, проданным из заявки."
        ),
    )
    monthly = Section(
        "По месяцам",
        [
            Column("Месяц", "date", 12),
            Column("Источник", width=24),
            Column("Заявок", "count", 10),
            Column("Купили", "count", 10),
        ],
        [
            [row["month"], row["label"] or NOT_SET, row["leads"], row["purchased"]]
            for row in sources_by_month(scope, period, filters)
        ],
    )
    return [quality, monthly]


@report("teacher_workload", "Загрузка преподавателей")
def teacher_workload_report(scope, period, params):
    data = teacher_workload(scope, period, params.get("teacher_filters"))
    teachers = Section(
        "Преподаватели",
        [
            Column("Преподаватель", width=28),
            Column("Занятий в неделю", "decimal", 18, total=False),
            Column("Учеников", "count", 12),
            Column("Запланировано", "count", 16),
            Column("Проведено", "count", 12),
            Column("Отменено", "count", 12),
            Column("По причине преподавателя", "count", 22),
            Column("Заполняемость групп, %", "percent", 22, total=False),
        ],
        [
            [
                row["name"],
                row["lessons_per_week"],
                row["students"],
                row["planned"],
                row["completed"],
                row["cancelled"],
                row["teacher_cancelled"],
                row["fill_percent"],
            ]
            for row in data["teachers"]
        ],
        note=(
            "Отчёт показывает объём нагрузки, а не качество работы. Число учеников зависит "
            "от направления, возраста групп и времени занятий."
        ),
    )
    trend = Section(
        "Динамика по месяцам",
        [
            Column("Месяц", "date", 14),
            Column("Преподаватель", width=28),
            Column("Запланировано", "count", 16),
            Column("Проведено", "count", 12),
            Column("Отменено", "count", 12),
            Column("Учеников", "count", 12),
            Column("Заполняемость, %", "percent", 18, total=False),
        ],
        [
            [
                point["date"],
                teacher["name"],
                point["planned"],
                point["completed"],
                point["cancelled"],
                point["students"],
                point["fill_percent"],
            ]
            for teacher in data["teachers"]
            for point in teacher["trend"]
        ],
    )
    cancellations = Section(
        "Причины отмен",
        [
            Column("Причина", width=30),
            Column("Отменено", "count", 12),
            Column("Связано с преподавателем", width=24),
        ],
        [
            [row["label"], row["value"], "Да" if row["teacher_fault"] else "Нет"]
            for row in data["cancel_reasons"]
        ],
    )
    sections = [teachers, trend, cancellations]
    for key, title, label in (
        ("branch", "По филиалам", "Филиал"),
        ("direction", "По направлениям", "Направление"),
    ):
        sections.append(
            Section(
                title,
                [
                    Column(label, width=26),
                    Column("Преподавателей", "count", 16),
                    Column("Учеников", "count", 12),
                    Column("Запланировано", "count", 16),
                    Column("Проведено", "count", 12),
                    Column("Отменено", "count", 12),
                ],
                [
                    [
                        row["label"],
                        row["teachers"],
                        row["students"],
                        row["planned"],
                        row["completed"],
                        row["cancelled"],
                    ]
                    for row in data["breakdowns"][key]
                ],
            )
        )
    return sections


@report("rejections", "Причины отказов")
def rejections_report(scope, period, params):
    kind = params.get("kind", "new")
    filters = params.get("funnel_filters") or {}
    data = rejections(scope, period, kind, filters)
    what = "продлений" if kind == "renewal" else "новых заявок"
    reasons = Section(
        "Причины",
        [
            Column("Причина", width=26),
            Column("Отказов", "count", 10),
            Column("Доля, %", "percent", 10),
            *[Column(label, "count", 14) for _, label, _ in REJECTION_STAGES],
        ],
        [
            [
                item["label"] or NOT_SET,
                item["value"],
                item["share"],
                *[item["stages"][key] for key, _, _ in REJECTION_STAGES],
            ]
            for item in data["reasons"]
        ],
        note=(
            f"Отказы {what}, случившиеся за период. Потеря контакта («не пришёл на пробное») "
            f"не входит — {data['lost_contact']} таких отдельно."
        ),
    )
    lost = Section(
        "Потеря контакта",
        [Column("Причина", width=26), Column("Отказов", "count", 10)],
        [[item["label"] or NOT_SET, item["value"]] for item in data["lost_contact_reasons"]],
    )
    monthly = Section(
        "По месяцам",
        [Column("Месяц", "date", 12), Column("Причина", width=26), Column("Отказов", "count", 10)],
        [[row["month"], row["label"] or NOT_SET, row["value"]] for row in data["by_month"]],
    )
    by_source = Section(
        "По источникам",
        [
            Column("Источник", width=24),
            Column("Отказов", "count", 10),
            Column("Главная причина", width=24),
            Column("Её доля, %", "percent", 12),
        ],
        [
            [
                item["label"] or NOT_SET,
                item["value"],
                item["top_reason"] or NOT_SET,
                item["top_share"],
            ]
            for item in rejections_by(scope, period, "source", kind, filters)
        ],
    )
    comments = Section(
        "Комментарии",
        [
            Column("Дата", "date", 12),
            Column("Заявка", width=24),
            Column("Причина", width=22),
            Column("Этап", width=18),
            Column("Комментарий", width=60),
        ],
        [
            [row["date"][:10], row["lead"], row["reason"] or NOT_SET, row["stage"], row["comment"]]
            for row in rejection_comments(scope, period, kind, filters)
        ],
    )
    return [reasons, lost, monthly, by_source, comments]


@report("branches", "Сравнение филиалов")
def branches_report(scope, period, params):
    data = compare_branches(scope, period)
    columns = [Column("Филиал", width=24)]
    for column in BRANCH_COLUMNS:
        title = f"{column.label}{UNIT_TITLE[column.unit]}"
        columns.append(Column(title, column.unit, 16, total=False))
    rows = [
        [row["branch"]["name"], *[row["values"][c.key]["value"] for c in BRANCH_COLUMNS]]
        for row in data["rows"]
    ]
    rows.append(["Всего по выборке", *[data["total"][c.key]["value"] for c in BRANCH_COLUMNS]])
    return [
        Section(
            "Филиалы",
            columns,
            rows,
            note=(
                "Сравнивать честно по относительным колонкам: на ребёнка, доли, конверсия. "
                "Ребёнок — ходил на занятия в периоде. Задолженность — на сегодня."
            ),
        )
    ]


@report("risk_list", "Риск-лист — в зоне ухода")
def risk_list_report(scope, period, params):
    data = risk_list(scope, period)
    signal_labels = {
        "attendance": "Участились пропуски",
        "subscription": "Абонемент заканчивается или истёк",
        "debt": "Есть задолженность",
    }
    return [
        Section(
            "Риск-лист",
            [
                Column("Ребёнок", width=28),
                Column("Уровень", width=14),
                Column("Сигналы", width=54),
                Column("Пропусков", "count", 13, total=False),
                Column("Рост к норме, п.п.", "percent", 18, total=False),
                Column("Абонемент", width=24),
                Column("Долг, ₸", "money", 14),
                Column("Филиал", width=20),
                Column("Направление", width=20),
                Column("Родитель", width=24),
                Column("Телефон", width=18),
            ],
            [
                [
                    row["name"],
                    "Срочно" if row["level"] == "urgent" else "Внимание",
                    ", ".join(signal_labels[key] for key in row["signals"]),
                    (row["attendance"] or {}).get("absences"),
                    (row["attendance"] or {}).get("absence_change_pp"),
                    (row["subscription"] or {}).get("name"),
                    row["debt"],
                    row["branch"],
                    row["direction"],
                    row.get("parent"),
                    row.get("phone"),
                ]
                for row in data["items"]
            ],
            note=(
                "Один сигнал — внимание, два или три — срочно. "
                "Пороги пропусков настраиваются в настройках организации."
            ),
        )
    ]


def build(name, scope, period, params=None) -> Export:
    spec = REPORTS[name]
    return Export(
        spec.title, spec.build(scope, period, params or {}), (params or {}).get("filter_labels", [])
    )
