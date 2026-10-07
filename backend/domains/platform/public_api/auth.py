"""Ключи публичного API: выдача, проверка, лимиты (TRU-176)."""

import secrets

from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission
from rest_framework.throttling import SimpleRateThrottle

from domains.platform.tenants.plans import has_feature

from .models import ApiKey, hash_key

KEY_PREFIX = "kc_live_"
# Обновлять «последнее использование» не чаще раза в минуту — без записи в
# базу на каждый запрос.
LAST_USED_EVERY = 60


def issue_key(organization, *, name, scope, branches, user) -> tuple[ApiKey, str]:
    """Новый ключ. Возвращает (запись, ключ целиком) — целиком он больше
    нигде не хранится и не показывается."""
    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    key = ApiKey.objects.create(
        organization=organization,
        name=name,
        prefix=raw[: len(KEY_PREFIX) + 6],
        key_hash=hash_key(raw),
        scope=scope,
        created_by=user,
    )
    key.branches.set(branches)
    return key, raw


class ApiKeyPrincipal:
    """request.user для запроса по ключу: не сотрудник, у него нет роли —
    только организация, область и филиалы ключа."""

    is_authenticated = True
    is_anonymous = False
    is_staff = False

    def __init__(self, key: ApiKey):
        self.key = key
        self.pk = key.pk
        self.organization = key.organization
        self.organization_id = key.organization_id

    def __str__(self) -> str:
        return f"api-key:{self.key.prefix}"


class ApiKeyAuthentication(BaseAuthentication):
    """`Authorization: Bearer kc_live_…` или `X-Api-Key: kc_live_…`."""

    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        raw = header[7:].strip() if header.startswith("Bearer ") else ""
        raw = raw or request.META.get("HTTP_X_API_KEY", "").strip()
        if not raw:
            return None
        if not raw.startswith(KEY_PREFIX):
            raise exceptions.AuthenticationFailed("Неверный ключ API.")
        key = (
            ApiKey.objects.select_related("organization")
            .filter(key_hash=hash_key(raw), revoked_at__isnull=True)
            .first()
        )
        if key is None or not key.organization.is_active:
            raise exceptions.AuthenticationFailed("Ключ API не найден или отозван.")
        now = timezone.now()
        if key.last_used_at is None or (now - key.last_used_at).total_seconds() > LAST_USED_EVERY:
            ApiKey.objects.filter(pk=key.pk).update(last_used_at=now)
        return ApiKeyPrincipal(key), key

    def authenticate_header(self, request):
        return 'Bearer realm="kidscrm-public-api"'


class HasPublicApi(BasePermission):
    """Ключ есть, тариф Enterprise, запись — только ключом «чтение и запись»."""

    message = "Публичное API доступно на тарифе Enterprise."

    def has_permission(self, request, view):
        key = request.auth
        if not isinstance(key, ApiKey):
            return False
        if not has_feature(key.organization, "public_api"):
            self.message = "Публичное API доступно на тарифе Enterprise."
            return False
        if (
            request.method not in ("GET", "HEAD", "OPTIONS")
            and key.scope != ApiKey.Scope.READ_WRITE
        ):
            self.message = "У ключа только чтение."
            return False
        return True


class _KeyThrottle(SimpleRateThrottle):
    def get_cache_key(self, request, view):
        key = request.auth
        if not isinstance(key, ApiKey):
            return None
        return self.cache_format % {"scope": self.scope, "ident": key.pk}


class PerMinuteThrottle(_KeyThrottle):
    scope = "public_api_minute"
    THROTTLE_RATES = {"public_api_minute": "60/min"}


class PerDayThrottle(_KeyThrottle):
    scope = "public_api_day"
    THROTTLE_RATES = {"public_api_day": "20000/day"}
