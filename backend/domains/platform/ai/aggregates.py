"""
Слой обезличенных агрегатов для ИИ-помощника (TRU-158, ADR-0009 раздел 3).

Единственная точка, через которую данные CRM идут в дайджест: функции
помощника не обращаются к моделям напрямую, только сюда. Каждая функция
возвращает числа и названия центра (группы, направления, филиалы,
источники) — не людей:

- цифры берутся из сервисов аналитики (ADR-0006), не пересчитываются —
  дайджест и дашборд не расходятся;
- id сущностей, комментарии и свободный текст не выдаются;
- срезы с деньгами и пропусками — только если в срезе не меньше
  MIN_GROUP детей или заявок (иначе «обезличенная» цифра указывает на семью);
- результат дополнительно проходит псевдонимы (ADR-0008): имя ребёнка,
  попавшее, например, в название индивидуальной группы, уйдёт меткой.

Новая функция слоя вносится в AGGREGATES — tests_aggregates.py прогоняет
их все и падает, если в выводе нашлось имя, телефон, почта или id; функция
не из списка роняет тест тоже.
"""

import re
from datetime import timedelta

from domains.people.clients.models import Child
from domains.platform.analytics.funnel import funnel
from domains.platform.analytics.group_occupancy import group_occupancy
from domains.platform.analytics.period import Period, _add_months, period_for
from domains.platform.analytics.registry import compute
from domains.platform.analytics.rejections import rejections
from domains.platform.analytics.scope import Scope
from domains.platform.analytics.sources import sources_quality
from domains.platform.core.utils import today_for_org

from .pseudonyms import Pseudonymizer

MIN_GROUP = 5
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
# Ключи, которые наружу не выдаются никогда.
DROP_KEYS = {"id", "key", "merge_candidates", "comment", "comments", "source"}
AGE_BANDS = ((3, 4), (5, 6), (7, 9), (10, 13), (14, 17))
SEASON_METRICS = ("new_leads", "revenue", "active_children")


def _scope(organization) -> Scope:
    return Scope(organization, None, [])


def _period(organization) -> Period:
    return period_for("month", today_for_org(organization))


def _strip(value):
    """Без id, комментариев и служебных полей экрана."""
    if isinstance(value, dict):
        return {
            k: _strip(v)
            for k, v in value.items()
            if k not in DROP_KEYS and not (isinstance(v, str) and UUID.match(v))
        }
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def occupancy(organization) -> dict:
    """Заполняемость групп: сколько занято из скольких мест, что недобрано."""
    data = group_occupancy(_scope(organization), _period(organization))
    return {
        "итого": data["summary"],
        "порог_недобора_процент": data["threshold"],
        "группы": [
            {
                "группа": g["name"],
                "филиал": g["branch"],
                "направление": g["direction"],
                "занято": g["occupied"],
                "мест": g["capacity"],
                "процент": g["percent"],
                "недобор": g["is_underfilled"],
                "совет_системы": g["suggested_action"],
            }
            for g in data["groups"]
        ],
    }


def conversion(organization) -> dict:
    """Воронка новых заявок за текущий месяц и прошлый — по этапам."""
    data = funnel(_scope(organization), _period(organization))

    def stages(summary):
        return {
            "заявок": summary["total"],
            "этапы": {s["label"]: s["count"] for s in summary["stages"]},
            "конверсия_процент": summary["conversion"],
            "думают": summary["thinking"],
            "отказ": summary["rejected"],
        }

    return {
        "этот_месяц": stages(data),
        "прошлый_месяц": stages(data["previous"]) if data.get("previous") else None,
    }


def sources(organization) -> list:
    """Источники заявок: сколько заявок, пробных, покупок. Деньги по
    источнику — только если заявок не меньше MIN_GROUP."""
    rows = []
    for row in sources_quality(_scope(organization), _period(organization)):
        item = {
            "источник": row["label"],
            "заявок": row["leads"],
            "пробных": row["trial"],
            "купили": row["purchased"],
            "конверсия_процент": row["conversion"],
            "мало_данных": row["small_sample"],
        }
        if row["leads"] >= MIN_GROUP:
            item["выручка"] = row["revenue"]
            item["средний_чек"] = row["avg_check"]
        rows.append(item)
    return rows


def rejection_reasons(organization) -> dict:
    """Причины отказов за месяц — числа, без комментариев."""
    data = rejections(_scope(organization), _period(organization))
    return {
        "всего": data["total"],
        "по_существу": data["real"],
        "потеря_контакта": data["lost_contact"],
        "причины": {r["label"]: r["value"] for r in data["reasons"]},
        "на_каком_этапе": {s["label"]: s["value"] for s in data["stages"]},
    }


def ages(organization) -> dict:
    """Активные дети по возрастным группам — только количество."""
    today = today_for_org(organization)
    counts = {f"{lo}–{hi}": 0 for lo, hi in AGE_BANDS}
    counts["другой"] = 0
    for birth in (
        Child.objects.for_tenant(organization)
        .filter(status=Child.Status.ACTIVE)
        .values_list("birth_date", flat=True)
    ):
        age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
        band = next((f"{lo}–{hi}" for lo, hi in AGE_BANDS if lo <= age <= hi), "другой")
        counts[band] += 1
    return counts


def money(organization) -> dict | None:
    """Деньги по центру за месяц. Нет при малом центре (меньше MIN_GROUP
    активных детей): иначе сумма долга указывает на конкретные семьи."""
    if (
        Child.objects.for_tenant(organization).filter(status=Child.Status.ACTIVE).count()
        < MIN_GROUP
    ):
        return None
    data = compute(
        ["revenue", "average_check", "debt_total"],
        _scope(organization),
        _period(organization),
        series=False,
    )
    return {
        data[name]["label"]: {"значение": data[name]["value"], "было": data[name].get("previous")}
        for name in data
    }


def seasonality(organization) -> dict:
    """Помесячно за 13 месяцев: тот же месяц прошлого года и тренд —
    иначе совет «продвигайте балет» выйдет в июле, когда его не продвигает
    никто."""
    today = today_for_org(organization)
    first = today.replace(day=1)
    scope = _scope(organization)
    result = {name: [] for name in SEASON_METRICS}
    labels = {}
    for back in range(12, -1, -1):
        start = _add_months(first, -back)
        end = min(_add_months(start, 1) - timedelta(days=1), today)
        data = compute(list(SEASON_METRICS), scope, Period(start, end), compare=False, series=False)
        for name in SEASON_METRICS:
            labels[name] = data[name]["label"]
            result[name].append({"месяц": start.strftime("%Y-%m"), "значение": data[name]["value"]})
    return {labels[name]: rows for name, rows in result.items()}


# Всё, что слой отдаёт наружу. Новая функция — сюда, иначе тест упадёт.
AGGREGATES = {
    "occupancy": occupancy,
    "conversion": conversion,
    "sources": sources,
    "rejection_reasons": rejection_reasons,
    "ages": ages,
    "money": money,
    "seasonality": seasonality,
}


def snapshot(organization) -> dict:
    """Всё для дайджеста одним словарём — уже без людей."""
    names = Pseudonymizer(organization)
    return {name: names.mask(_strip(func(organization))) for name, func in AGGREGATES.items()}
