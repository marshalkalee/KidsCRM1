"""
Пороги автостатусов организации (ТЗ п. 4.4) — единая точка правды.

Хранятся в Organization.settings (JSONField), не отдельными колонками —
это ключи одного словаря, настраиваемые владельцем на экране "Настройки
организации" (см. web_views.organization_settings). На них будут
опираться экраны Bekzat (продления, задолженности) и аналитика в M3 —
поэтому именно здесь, а не разбросанными хардкодами по доменам:
domains.money.* должен читать пороги через get_org_setting(), а не
подставлять свои числа.
"""

SUBSCRIPTION_ENDING_LESSONS_THRESHOLD = "subscription_ending_lessons_threshold"
SUBSCRIPTION_ENDING_DAYS_THRESHOLD = "subscription_ending_days_threshold"
DEBT_OVERDUE_DAYS_THRESHOLD = "debt_overdue_days_threshold"
GROUP_UNDERFILLED_PERCENT_THRESHOLD = "group_underfilled_percent_threshold"

DEFAULT_ORG_SETTINGS = {
    # Абонемент "заканчивается", когда остаётся <= N занятий ИЛИ <= N дней.
    SUBSCRIPTION_ENDING_LESSONS_THRESHOLD: 3,
    SUBSCRIPTION_ENDING_DAYS_THRESHOLD: 7,
    # Задолженность считается просроченной, если старше N дней.
    DEBT_OVERDUE_DAYS_THRESHOLD: 5,
    # Группа считается недозаполненной при заполненности < X% вместимости.
    GROUP_UNDERFILLED_PERCENT_THRESHOLD: 50,
}


def get_org_setting(organization, key):
    """Порог с фолбэком на дефолт — так у новых организаций не пустое поведение."""
    return organization.settings.get(key, DEFAULT_ORG_SETTINGS[key])
