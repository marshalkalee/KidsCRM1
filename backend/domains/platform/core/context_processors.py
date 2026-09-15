"""
Контекст-процессоры каркаса — доступны во всех шаблонах без повторения в
каждой view. Не бизнес-логика, только то, что нужно layout'у (шапка,
боковая навигация, переключатель филиала).
"""

from domains.platform.core.role_permissions import get_user_permissions


def branches(request):
    """
    Реальные филиалы текущей организации + выбранный (сессия) — для
    переключателя в шапке. Пусто для анонимного пользователя/платформенного
    суперпользователя без organization (см. users/models.py).
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or user.organization_id is None:
        return {"kc_branches": [], "kc_active_branch": None}

    from domains.platform.tenants.models import Branch

    available = list(Branch.objects.for_tenant(user.organization).order_by("name"))
    active_id = request.session.get("active_branch_id")
    active = None
    if active_id:
        active = next((b for b in available if str(b.id) == str(active_id)), None)
    if active is None and available:
        active = available[0]

    return {"kc_branches": available, "kc_active_branch": active}


def user_permissions(request):
    """Гранулярные права текущего пользователя — см. core/role_permissions.py."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"kc_permissions": {}}
    return {"kc_permissions": get_user_permissions(user)}
