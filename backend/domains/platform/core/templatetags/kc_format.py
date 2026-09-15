"""
Форматирование дат/времени/денег по локали и часовому поясу организации
(ТЗ п. 10.1). Деньги — тонкая обёртка над `core.utils.format_tenge`
(Дарья), чтобы не дублировать округление/формат в двух местах.

Теги, а не фильтры — фильтр не может сам достать organization текущего
пользователя из контекста, а передавать его в каждый шаблон вручную
означает рано или поздно забыть и получить сервер-таймзону вместо
таймзоны организации.
"""

import pytz
from django import template
from django.utils import timezone as dj_timezone

from domains.platform.core.utils import format_tenge

register = template.Library()


def _org_timezone(context):
    request = context.get("request")
    user = getattr(request, "user", None) if request else None
    organization = getattr(user, "organization", None) if user else None
    tz_name = getattr(organization, "timezone", None)
    if not tz_name:
        return dj_timezone.get_default_timezone()
    return pytz.timezone(tz_name)


@register.simple_tag(takes_context=True)
def kc_datetime(context, value, fmt="%d.%m.%Y %H:%M"):
    if value is None:
        return ""
    return dj_timezone.localtime(value, _org_timezone(context)).strftime(fmt)


@register.simple_tag(takes_context=True)
def kc_date(context, value, fmt="%d.%m.%Y"):
    if value is None:
        return ""
    return dj_timezone.localtime(value, _org_timezone(context)).strftime(fmt)


@register.simple_tag
def kc_money(value):
    if value is None:
        return ""
    return format_tenge(value)
