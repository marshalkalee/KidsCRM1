"""
Версия кэша аналитики центра (TRU-123). Отчёты за закрытые периоды держатся
в кэше час, а оплату могут отменить задним числом: без сброса владелец час
видел бы старую выручку прошлого месяца. Версия входит в ключ каждой записи
(Scope.cache_key); сброс — новая версия, старые записи просто не читаются
и сами истекают по TTL.
"""

import logging
import uuid

from django.core.cache import caches

CACHE_ALIAS = "analytics"
logger = logging.getLogger(__name__)


def _key(organization_id) -> str:
    return f"epoch:{organization_id}"


def epoch_of(organization_id) -> str:
    try:
        return caches[CACHE_ALIAS].get(_key(organization_id)) or "0"
    except Exception:
        logger.warning("analytics cache unavailable", exc_info=True)
        return "0"


def bump_epoch(organization_id) -> None:
    try:
        caches[CACHE_ALIAS].set(_key(organization_id), uuid.uuid4().hex[:8], None)
    except Exception:
        logger.warning("analytics cache unavailable", exc_info=True)
