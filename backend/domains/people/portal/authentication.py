"""
Токен кабинета родителя: заголовок «Authorization: Parent <токен>».

Отдельная схема, а не JWT сотрудников: эндпоинты CRM принимают только
JWT (REST_FRAMEWORK.DEFAULT_AUTHENTICATION_CLASSES), поэтому токен
родителя туда не пустит — даже если кто-то подставит его в запрос к
/api/v1/clients/... Эндпоинты кабинета, наоборот, принимают только его.
"""

from rest_framework import authentication, exceptions
from rest_framework.permissions import BasePermission

from .auth import session_for_token

KEYWORD = "Parent"


class ParentTokenAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode(errors="ignore").split()
        if not header or header[0] != KEYWORD:
            return None
        if len(header) != 2:
            raise exceptions.AuthenticationFailed("Неверный заголовок авторизации.")
        session = session_for_token(header[1])
        if session is None:
            raise exceptions.AuthenticationFailed("Сессия истекла — войдите заново.")
        return session.account, session

    def authenticate_header(self, request):
        return KEYWORD


class IsParent(BasePermission):
    def has_permission(self, request, view):
        return request.auth is not None and getattr(request.auth, "account_id", None) is not None


def request_meta(request) -> dict:
    """IP — от nginx (X-Real-IP), иначе адрес соединения."""
    return {
        "ip": request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR"),
        "user_agent": request.META.get("HTTP_USER_AGENT", ""),
    }
