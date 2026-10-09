"""
Активный филиал для API (frontend2, TRU-80). В старом вебе выбор жил в
сессии (core.views.switch_branch); фронт на JWT присылает его заголовком
`X-Branch-Id` на каждый запрос.

Нет заголовка — «все филиалы» (None). Филиал чужой организации или
архивный — тоже None, а не ошибка: заголовок не должен ни ломать запрос,
ни открывать чужие данные. Списки, которые умеют фильтровать по филиалу,
берут его отсюда (список детей — TRU-81 и т.д.).

Филиалы сотрудника: у кого в профиле выбраны филиалы (кроме владельца),
тот работает только в них — чужой филиал в заголовке не действует, а
«все филиалы» значит «все свои» (branch_scope). Не выбран ни один —
работает во всех, как раньше.
"""

import uuid

from domains.platform.tenants.models import Branch

HEADER = "HTTP_X_BRANCH_ID"


def allowed_branch_ids(user) -> list | None:
    """Филиалы, в которых сотрудник работает; None — все филиалы организации."""
    from domains.platform.users.models import User

    if user is None or not user.is_authenticated or user.role == User.Role.OWNER:
        return None
    cached = getattr(user, "_allowed_branch_ids", "unset")
    if cached == "unset":
        cached = list(user.branches.filter(is_active=True).values_list("id", flat=True)) or None
        user._allowed_branch_ids = cached
    return cached


def _parse(raw):
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError):
        return None


def get_active_branch(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or not user.organization_id:
        return None
    allowed = allowed_branch_ids(user)
    branch_id = _parse(request.META.get(HEADER))
    if branch_id is not None and allowed is not None and branch_id not in allowed:
        branch_id = None
    if branch_id is None:
        return None
    return Branch.objects.for_tenant(user.organization).filter(pk=branch_id, is_active=True).first()


def branch_scope(request, requested=None) -> list | None:
    """Филиалы для фильтра списка: явный ?branch= (если он сотруднику
    доступен), иначе филиал из шапки, иначе все его филиалы. None — без
    фильтра (все филиалы организации)."""
    allowed = allowed_branch_ids(getattr(request, "user", None))
    branch_id = _parse(requested)
    if branch_id is not None and (allowed is None or branch_id in allowed):
        return [branch_id]
    active = get_active_branch(request)
    if active is not None:
        return [active.id]
    return allowed
