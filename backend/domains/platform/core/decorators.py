"""
Защита обычных Django-страниц по ролям — не API (там своя защита, см.
core/permissions.py + core/role_permissions.py, DRF/JWT). Страницы держатся
на обычной сессии Django (см. web_auth.py), поэтому и защита — обычным
Django-декоратором, а не через DRF permission classes.
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def role_required(*roles):
    """
    @role_required() без аргументов — просто "залогинен и привязан к
    организации" (как IsStaffOfOrganization для API). С аргументами —
    роль должна быть одной из перечисленных (User.Role.*).
    """

    def decorator(view_func):
        @wraps(view_func)
        @login_required(login_url="core:login")
        def wrapped(request, *args, **kwargs):
            if request.user.organization_id is None:
                raise PermissionDenied("Пользователь не привязан к организации.")
            if roles and request.user.role not in roles:
                raise PermissionDenied("Недостаточно прав для этой страницы.")
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator
