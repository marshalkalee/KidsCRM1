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


PHONE_VIEW_ROLES = {
    User.Role.OWNER,
    User.Role.MANAGER,
    User.Role.ADMIN,
    User.Role.ACCOUNTANT,
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


def can_view_phone(user) -> bool:
    return user.role in PHONE_VIEW_ROLES


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
    }
