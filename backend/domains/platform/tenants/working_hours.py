"""
Рабочие часы филиала — {"mon": {"closed": False, "open": "09:00", "close": "20:00"}, …}.
Одна проверка для веб-формы (BranchForm) и API (BranchSerializer), чтобы
филиал, сохранённый из React, выглядел так же, как из старого веба.
"""

import datetime

WEEKDAY_CODES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKEND = ("sat", "sun")
DEFAULT_OPEN = "09:00"
DEFAULT_CLOSE = "20:00"


def default_working_hours() -> dict:
    """Пн–пт 09:00–20:00, выходные закрыты — как начальные значения BranchForm."""
    return {
        code: {"closed": True}
        if code in WEEKEND
        else {"closed": False, "open": DEFAULT_OPEN, "close": DEFAULT_CLOSE}
        for code in WEEKDAY_CODES
    }


def _parse_time(value):
    try:
        return datetime.datetime.strptime(value, "%H:%M").time()
    except (TypeError, ValueError):
        return None


def normalize_working_hours(value) -> tuple[dict, dict]:
    """(working_hours, errors) — errors: {код дня: сообщение}. Недостающие
    дни получают значения по умолчанию, лишние ключи отбрасываются."""
    if not isinstance(value, dict):
        return {}, {"__all__": "Ожидается словарь по дням недели."}
    defaults = default_working_hours()
    result, errors = {}, {}
    for code in WEEKDAY_CODES:
        day = value.get(code)
        if not isinstance(day, dict):
            result[code] = defaults[code]
            continue
        if day.get("closed"):
            result[code] = {"closed": True}
            continue
        open_time, close_time = _parse_time(day.get("open")), _parse_time(day.get("close"))
        if open_time is None or close_time is None:
            errors[code] = "Укажите время в формате ЧЧ:ММ."
        elif close_time <= open_time:
            errors[code] = "Время закрытия должно быть позже открытия."
        result[code] = {"closed": False, "open": day.get("open"), "close": day.get("close")}
    return result, errors
