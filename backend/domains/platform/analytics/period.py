"""
Период отчёта (TRU-118, для каркаса дашборда TRU-113): один разбор на все
отчёты, чтобы «месяц» не значил в двух отчётах разное.

Даты — календарные дни центра (часовой пояс организации), обе границы
включительно. Текущий период идёт «по сегодня», а прошлый для сравнения —
той же длины на единицу раньше: 1–15 сентября сравниваем с 1–15 августа,
а не с целым августом, иначе любой незаконченный месяц выглядит падением.
"""

import calendar
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta

import pytz

from domains.platform.core.utils import today_for_org

STEPS = ("day", "week", "month")
PRESETS = ("today", "week", "month", "quarter", "year", "custom")
DEFAULT_PRESET = "month"
# Больше года за раз не считаем: отчёт превращается в выгрузку базы.
MAX_DAYS = 366


class PeriodError(ValueError):
    """Период не разобрать — текст для пользователя."""


@dataclass(frozen=True)
class Period:
    start: date
    end: date
    preset: str = "custom"
    # Шаг графика, выбранный пользователем (day / week / month); пусто —
    # по длине периода, см. granularity.
    step: str = ""

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def granularity(self) -> str:
        """Шаг графика: выбранный пользователем, иначе по длине периода —
        до месяца по дням, до полугода по неделям."""
        if self.step:
            return self.step
        if self.days <= 31:
            return "day"
        if self.days <= 184:
            return "week"
        return "month"

    def previous(self) -> "Period":
        if self.preset in ("month", "quarter", "year"):
            months = {"month": 1, "quarter": 3, "year": 12}[self.preset]
            start = _add_months(self.start, -months)
            end = min(start + timedelta(days=self.days - 1), self.start - timedelta(days=1))
            return Period(start, end, self.preset, self.step)
        return Period(
            self.start - timedelta(days=self.days),
            self.start - timedelta(days=1),
            self.preset,
            self.step,
        )

    def bounds(self, organization) -> tuple[datetime, datetime]:
        """[начало первого дня, начало дня после последнего) в поясе центра —
        для фильтра по DateTimeField: `field__gte=a, field__lt=b`."""
        tz = pytz.timezone(organization.timezone)
        return (
            tz.localize(datetime.combine(self.start, time.min)),
            tz.localize(datetime.combine(self.end + timedelta(days=1), time.min)),
        )

    def bucket_starts(self) -> list[date]:
        """Начала корзин графика — чтобы пустые дни были нулями, а не дырами."""
        step = self.granularity
        current = bucket_start(self.start, step)
        starts = []
        while current <= self.end:
            starts.append(current)
            if step == "day":
                current += timedelta(days=1)
            elif step == "week":
                current += timedelta(days=7)
            else:
                current = _add_months(current, 1)
        return starts

    def as_dict(self) -> dict:
        return {
            "preset": self.preset,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "days": self.days,
            "granularity": self.granularity,
        }


def bucket_start(day: date, granularity: str) -> date:
    if granularity == "week":
        return day - timedelta(days=day.weekday())
    if granularity == "month":
        return day.replace(day=1)
    return day


def _add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year, month = day.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def period_for(preset: str, today: date, start=None, end=None, step: str = "") -> Period:
    period = _preset_period(preset, today, start, end)
    if step:
        if step not in STEPS:
            raise PeriodError("Шаг графика: day, week или month.")
        period = replace(period, step=step)
    return period


def _preset_period(preset: str, today: date, start, end) -> Period:
    if preset == "today":
        return Period(today, today, preset)
    if preset == "week":
        return Period(today - timedelta(days=today.weekday()), today, preset)
    if preset == "month":
        return Period(today.replace(day=1), today, preset)
    if preset == "quarter":
        first_month = (today.month - 1) // 3 * 3 + 1
        return Period(today.replace(month=first_month, day=1), today, preset)
    if preset == "year":
        return Period(today.replace(month=1, day=1), today, preset)
    if preset == "custom":
        if start is None or end is None:
            raise PeriodError("Укажите начало и конец периода.")
        end = min(end, today)
        if start > end:
            raise PeriodError("Начало периода позже конца.")
        if (end - start).days + 1 > MAX_DAYS:
            raise PeriodError("Период больше года — выберите короче.")
        return Period(start, end, preset)
    raise PeriodError("Неизвестный период.")


def parse_period(params, organization) -> Period:
    """?period=month | ?period=custom&from=2026-01-01&to=2026-03-31;
    ?granularity=day|week|month — шаг графика (TRU-123), иначе по длине периода."""
    preset = params.get("period") or DEFAULT_PRESET
    try:
        start = date.fromisoformat(params["from"]) if params.get("from") else None
        end = date.fromisoformat(params["to"]) if params.get("to") else None
    except ValueError as exc:
        raise PeriodError("Дата в формате ГГГГ-ММ-ДД.") from exc
    return period_for(
        preset, today_for_org(organization), start, end, params.get("granularity") or ""
    )
