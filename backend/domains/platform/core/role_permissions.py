"""
Гранулярные права по ролям.
Используется для настраиваемых ограничений — например, скрыть телефоны
от преподавателей (V2). Базовые права ролей — в permissions.py.
"""

from domains.platform.users.models import User

FINANCE_ROLES = {
    User.Role.OWNER,
    User.Role.ACCOUNTANT,
}

SCHEDULE_EDIT_ROLES = {
    User.Role.OWNER,
    User.Role.MANAGER,
    User.Role.ADMIN,
}

STAFF_MANAGE_ROLES = {
    User.Role.OWNER,
    User.Role.MANAGER,
}

ORG_SUMMARY_ROLES = {
    User.Role.OWNER,
}

# Настройки организации (пороги автостатусов, часовой пояс) — только
# владелец (тикет "Настройки организации, филиалы и залы"). Отдельно от
# ORG_SUMMARY_ROLES: сегодня совпадают, но означают разное — сводка не то
# же самое, что право менять пороги, разойдутся, если позже дадут
# управляющему смотреть сводку без права её настраивать.
ORG_SETTINGS_MANAGE_ROLES = {
    User.Role.OWNER,
}

BRANCH_MANAGE_ROLES = {
    User.Role.OWNER,
    User.Role.MANAGER,
}

DIRECTION_MANAGE_ROLES = {
    User.Role.OWNER,
    User.Role.MANAGER,
}

GROUP_MANAGE_ROLES = {
    User.Role.OWNER,
    User.Role.MANAGER,
}

PHONE_VIEW_ROLES = {
    User.Role.OWNER,
    User.Role.MANAGER,
    User.Role.ADMIN,
    User.Role.ACCOUNTANT,
}

# Причина ухода и согласие на обработку данных — административные/
# аналитические поля карточки ребёнка, не нужны преподавателю в работе.
CHILD_SENSITIVE_FIELDS_ROLES = {
    User.Role.OWNER,
    User.Role.MANAGER,
    User.Role.ADMIN,
    User.Role.ACCOUNTANT,
}

# Деньги по конкретным детям и родителям — абонемент, долг, оплаты в
# списке детей и карточке родителя. Шире FINANCE_ROLES (там финансовые
# отчёты — владелец и бухгалтер): долг — ежедневный рабочий список
# администратора (ТЗ п. 4.1), а преподавателю в работе не нужен.
CLIENT_MONEY_VIEW_ROLES = {
    User.Role.OWNER,
    User.Role.MANAGER,
    User.Role.ADMIN,
    User.Role.ACCOUNTANT,
}

# Создать/изменить ребёнка, родителя, запустить импорт — те же роли, что
# у IsOwnerOrManagerOrAdmin на ChildViewSet/ParentContactViewSet.
CHILD_MANAGE_ROLES = {
    User.Role.OWNER,
    User.Role.MANAGER,
    User.Role.ADMIN,
}

# Заявки воронки продаж (TRU-99) — их разбирают администраторы и
# управляющие; преподавателю и бухгалтеру воронка в работе не нужна.
LEAD_MANAGE_ROLES = {
    User.Role.OWNER,
    User.Role.MANAGER,
    User.Role.ADMIN,
}

# Справочники воронки (источники, причины отказа — TRU-93) — как
# направления: настраивает владелец или управляющий, а не каждый
# администратор, иначе отчёты по источникам расползутся по синонимам.
LEAD_DICTIONARY_MANAGE_ROLES = {
    User.Role.OWNER,
    User.Role.MANAGER,
}


def can_view_financials(user) -> bool:
    return user.role in FINANCE_ROLES


def can_edit_schedule(user) -> bool:
    return user.role in SCHEDULE_EDIT_ROLES


def can_manage_staff(user) -> bool:
    return user.role in STAFF_MANAGE_ROLES


def can_view_org_summary(user) -> bool:
    return user.role in ORG_SUMMARY_ROLES


def can_manage_org_settings(user) -> bool:
    return user.role in ORG_SETTINGS_MANAGE_ROLES


def can_manage_branches(user) -> bool:
    return user.role in BRANCH_MANAGE_ROLES


def can_manage_directions(user) -> bool:
    return user.role in DIRECTION_MANAGE_ROLES


def can_manage_groups(user) -> bool:
    return user.role in GROUP_MANAGE_ROLES


def can_view_phone(user) -> bool:
    return user.role in PHONE_VIEW_ROLES


def can_view_child_sensitive_fields(user) -> bool:
    return user.role in CHILD_SENSITIVE_FIELDS_ROLES


def can_view_client_money(user) -> bool:
    return user.role in CLIENT_MONEY_VIEW_ROLES


def can_manage_children(user) -> bool:
    return user.role in CHILD_MANAGE_ROLES


def can_accept_payments(user) -> bool:
    """Принять и отменить оплату — как в API оплат (IsOwnerOrManagerOrAdmin)."""
    return user.role in CHILD_MANAGE_ROLES


def can_manage_leads(user) -> bool:
    return user.role in LEAD_MANAGE_ROLES


def can_manage_lead_dictionaries(user) -> bool:
    return user.role in LEAD_DICTIONARY_MANAGE_ROLES


# Аналитика владельца (M3, TRU-118): владелец — вся организация,
# управляющий — свои филиалы (analytics.scope). Администратору дашборд
# с выручкой не нужен — у него рабочие списки.
ANALYTICS_VIEW_ROLES = {
    User.Role.OWNER,
    User.Role.MANAGER,
}


def can_view_analytics(user) -> bool:
    return user.role in ANALYTICS_VIEW_ROLES


# Чат с ИИ на главной (ai/chat.py) — руководители и администратор: он
# отвечает по всей CRM в пределах прав сотрудника. Педагогам и бухгалтеру
# не включён — у них узкие задачи и свои экраны.
AI_CHAT_ROLES = {
    User.Role.OWNER,
    User.Role.MANAGER,
    User.Role.ADMIN,
}


def can_use_ai_chat(user) -> bool:
    return user.role in AI_CHAT_ROLES


def get_user_permissions(user) -> dict:
    return {
        "can_view_financials": can_view_financials(user),
        "can_edit_schedule": can_edit_schedule(user),
        "can_manage_staff": can_manage_staff(user),
        "can_view_org_summary": can_view_org_summary(user),
        "can_manage_org_settings": can_manage_org_settings(user),
        "can_manage_branches": can_manage_branches(user),
        "can_manage_directions": can_manage_directions(user),
        "can_view_phone": can_view_phone(user),
        "can_view_child_sensitive_fields": can_view_child_sensitive_fields(user),
        "can_manage_groups": can_manage_groups(user),
        "can_view_client_money": can_view_client_money(user),
        "can_manage_children": can_manage_children(user),
        "can_accept_payments": can_accept_payments(user),
        "can_manage_leads": can_manage_leads(user),
        "can_manage_lead_dictionaries": can_manage_lead_dictionaries(user),
        "can_view_analytics": can_view_analytics(user),
        "can_use_ai_chat": can_use_ai_chat(user),
    }
