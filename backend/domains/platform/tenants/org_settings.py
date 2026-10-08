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
# Что считать продлением (ТЗ п. 5.3, TRU-126): новый абонемент того же
# направления начался не позже N дней после окончания предыдущего.
RENEWAL_GRACE_DAYS = "renewal_grace_days"
# Отток (ТЗ раздел 7, TRU-127): «ушёл» — нет активного абонемента дольше
# N дней; летом — пауза до 30 сентября, а не уход.
CHURN_INACTIVE_DAYS = "churn_inactive_days"
CHURN_SUMMER_PAUSE = "churn_summer_pause"
RULE_LEAD_STALE_ENABLED = "rule_lead_stale_enabled"
RULE_RENEWAL_OFFER_ENABLED = "rule_renewal_offer_enabled"
RULE_DEBT_REMINDER_ENABLED = "rule_debt_reminder_enabled"
RULE_MISSING_SUBSCRIPTION_ENABLED = "rule_missing_subscription_enabled"
RULE_TRIAL_NO_SHOW_ENABLED = "rule_trial_no_show_enabled"
PARENT_CANCEL_NOTICE_HOURS = "parent_cancel_notice_hours"
PARENT_CANCEL_CHARGE_ON_TIME = "parent_cancel_charge_on_time"
# Доступ сотрудников внутри роли (TRU-153, ТЗ разд. 2 [V2]): владелец
# открывает роли то, что по умолчанию скрыто. Читаются только через
# core/role_permissions.py — там же API, выгрузки и флаги для фронтенда.
TEACHER_SEES_PARENT_PHONES = "teacher_sees_parent_phones"
TEACHER_SEES_FINANCES = "teacher_sees_finances"
ADMIN_SEES_ORG_SUMMARY = "admin_sees_org_summary"
# ИИ-функции, которые отправляют во внешнюю модель то, что загрузил
# сотрудник, как есть (ADR-0008): фото журнала с рукописными именами детей
# и файл клиентов нового центра. Метками их не закрыть — центр включает сам.
AI_ATTENDANCE_PHOTO_ENABLED = "ai_attendance_photo_enabled"
AI_IMPORT_CLEAN_ENABLED = "ai_import_clean_enabled"
# Еженедельный дайджест ИИ (TRU-163): день недели (0 — понедельник) и час
# по времени центра, когда он собирается и приходит владельцу.
DIGEST_WEEKDAY = "digest_weekday"
DIGEST_HOUR = "digest_hour"
# Рассылки родителям (TRU-168): тихие часы по времени центра (с какого часа
# и до какого не отправляем), порядок каналов с откатом, адрес для ответа
# на письма.
MESSAGING_QUIET_FROM = "messaging_quiet_from"
MESSAGING_QUIET_TO = "messaging_quiet_to"
MESSAGING_CHANNELS = "messaging_channels"
MESSAGING_REPLY_TO = "messaging_reply_to"
ACCESS_SETTINGS = (
    TEACHER_SEES_PARENT_PHONES,
    TEACHER_SEES_FINANCES,
    ADMIN_SEES_ORG_SUMMARY,
    AI_ATTENDANCE_PHOTO_ENABLED,
    AI_IMPORT_CLEAN_ENABLED,
)

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
    # Продлением считаем новый абонемент, начавшийся не позже N дней после
    # окончания прошлого. 14 — решение по умолчанию до ответа центра
    # (docs/project-status.md, вопрос №5): при 7 летний перерыв выглядит
    # как массовый отток. Читается только через renewal_conversion.grace_days().
    RENEWAL_GRACE_DAYS: 14,
    # Ушёл — нет активного абонемента дольше N дней. 30 и летняя пауза —
    # решения по умолчанию (docs/project-status.md, Д37 и Д38).
    # Читаются только через analytics/churn.py (churn_rules).
    CHURN_INACTIVE_DAYS: 30,
    CHURN_SUMMER_PAUSE: True,
    # Автоправила создания задач (TRU-108) — владелец может выключить любое.
    RULE_LEAD_STALE_ENABLED: True,
    RULE_RENEWAL_OFFER_ENABLED: True,
    RULE_DEBT_REMINDER_ENABLED: True,
    RULE_MISSING_SUBSCRIPTION_ENABLED: True,
    RULE_TRIAL_NO_SHOW_ENABLED: True,
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
    # Выключено, пока центр сам не согласится (решение 05.10.2026, TRU-156).
    AI_ATTENDANCE_PHOTO_ENABLED: False,
    AI_IMPORT_CLEAN_ENABLED: False,
    # Утро понедельника по времени центра (ТЗ п. 3.2).
    DIGEST_WEEKDAY: 0,
    DIGEST_HOUR: 9,
    # Ночью не пишем: напоминание об оплате в 23:40 — это жалоба.
    MESSAGING_QUIET_FROM: 21,
    MESSAGING_QUIET_TO: 9,
    # Первый доступный и доставленный — остальные не пробуем. Канала нет у
    # родителя или он не подключён центру — пропускается.
    MESSAGING_CHANNELS: ["push", "whatsapp", "email"],
    MESSAGING_REPLY_TO: "",
}


def get_org_setting(organization, key):
    """Порог с фолбэком на дефолт — так у новых организаций не пустое поведение."""
    return organization.settings.get(key, DEFAULT_ORG_SETTINGS[key])
