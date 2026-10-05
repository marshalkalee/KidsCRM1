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
RISK_ABSENCE_CHANGE_PP_THRESHOLD = "risk_absence_change_pp_threshold"
RISK_CURRENT_ABSENCES_MIN = "risk_current_absences_min"
LEAD_STALE_DAYS_THRESHOLD = "lead_stale_days_threshold"
RULE_LEAD_STALE_ENABLED = "rule_lead_stale_enabled"
RULE_RENEWAL_OFFER_ENABLED = "rule_renewal_offer_enabled"
RULE_DEBT_REMINDER_ENABLED = "rule_debt_reminder_enabled"
RULE_MISSING_SUBSCRIPTION_ENABLED = "rule_missing_subscription_enabled"
RULE_TRIAL_NO_SHOW_ENABLED = "rule_trial_no_show_enabled"
KASPI_PAYMENT_DETAILS = "kaspi_payment_details"
PARENT_CANCEL_NOTICE_HOURS = "parent_cancel_notice_hours"
PARENT_CANCEL_CHARGE_ON_TIME = "parent_cancel_charge_on_time"
# Доступ сотрудников внутри роли (TRU-153, ТЗ разд. 2 [V2]): владелец
# открывает роли то, что по умолчанию скрыто. Читаются только через
# core/role_permissions.py — там же API, выгрузки и флаги для фронтенда.
TEACHER_SEES_PARENT_PHONES = "teacher_sees_parent_phones"
TEACHER_SEES_FINANCES = "teacher_sees_finances"
ADMIN_SEES_ORG_SUMMARY = "admin_sees_org_summary"
ACCESS_SETTINGS = (TEACHER_SEES_PARENT_PHONES, TEACHER_SEES_FINANCES, ADMIN_SEES_ORG_SUMMARY)

DEFAULT_ORG_SETTINGS = {
    # Абонемент "заканчивается", когда остаётся <= N занятий ИЛИ <= N дней.
    SUBSCRIPTION_ENDING_LESSONS_THRESHOLD: 3,
    SUBSCRIPTION_ENDING_DAYS_THRESHOLD: 7,
    # Задолженность считается просроченной, если старше N дней.
    DEBT_OVERDUE_DAYS_THRESHOLD: 5,
    # Группа считается недозаполненной при заполненности < X% вместимости.
    GROUP_UNDERFILLED_PERCENT_THRESHOLD: 50,
    # Осторожный старт для риск-листа: сигнал появляется только при заметном
    # отклонении от личной нормы и хотя бы двух пропусках в выбранном периоде.
    RISK_ABSENCE_CHANGE_PP_THRESHOLD: 20,
    RISK_CURRENT_ABSENCES_MIN: 2,
    # Заявка считается "без движения", если статус не менялся N дней.
    LEAD_STALE_DAYS_THRESHOLD: 3,
    # Автоправила создания задач (TRU-108) — владелец может выключить любое.
    RULE_LEAD_STALE_ENABLED: True,
    RULE_RENEWAL_OFFER_ENABLED: True,
    RULE_DEBT_REMINDER_ENABLED: True,
    RULE_MISSING_SUBSCRIPTION_ENABLED: True,
    RULE_TRIAL_NO_SHOW_ENABLED: True,
    # Куда родителю платить по счёту из CRM без шлюза Kaspi: ссылка Kaspi
    # Pay или номер для перевода (payments/remote.py). Пусто — не настроено.
    KASPI_PAYMENT_DETAILS: "",
    # Родитель может предупредить и позже, но только своевременное
    # предупреждение применяет льготное правило центра. Значение хранится
    # здесь, чтобы кабинет, посещаемость и биллинг использовали один контракт.
    PARENT_CANCEL_NOTICE_HOURS: 24,
    PARENT_CANCEL_CHARGE_ON_TIME: False,
    # По умолчанию — поведение до TRU-153: преподаватель не видит телефоны
    # и деньги, администратор — аналитику.
    TEACHER_SEES_PARENT_PHONES: False,
    TEACHER_SEES_FINANCES: False,
    ADMIN_SEES_ORG_SUMMARY: False,
}


def get_org_setting(organization, key):
    """Порог с фолбэком на дефолт — так у новых организаций не пустое поведение."""
    return organization.settings.get(key, DEFAULT_ORG_SETTINGS[key])
