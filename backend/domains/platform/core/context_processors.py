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

    # Архивированный филиал (is_active=False) пропадает из выбора (ТЗ,
    # критерий приёмки тикета "Настройки организации, филиалы и залы"), но
    # его исторические данные остаются доступны через обычный for_tenant()
    # везде, где фильтр по is_active не применяется явно.
    available = list(
        Branch.objects.for_tenant(user.organization).filter(is_active=True).order_by("name")
    )
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


# Названия — в родном языке каждого варианта (Русский/Қазақша/English), а не
# переведённые: так их узнают независимо от того, какой язык выбран сейчас
# (тот же принцип, что у переключателей языка в других продуктах).
LANGUAGES = [
    ("ru", "Русский"),
    ("kk", "Қазақша"),
    ("en", "English"),
]


def language(request):
    """
    Текущий язык интерфейса — для переключателя в шапке и <html lang> в
    base.html/base_minimal.html. Хранится в сессии (см. switch_language),
    не в cookie/localStorage — по той же причине, что и активный филиал.
    """
    current = request.session.get("lang", "ru")
    if current not in dict(LANGUAGES):
        current = "ru"
    return {"kc_lang": current, "kc_languages": LANGUAGES}
