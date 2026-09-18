"""Настройки для продакшена. Регион хостинга — открытый вопрос (см. ADR-002)."""

from .base import *  # noqa: F403
from .base import env

DEBUG = False
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")

# nginx терминирует TLS и проксирует на backend по обычному HTTP внутри
# docker-сети — без этой настройки Django считает каждый запрос HTTP и
# уходит в бесконечный редирект на SECURE_SSL_REDIRECT.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 7
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
