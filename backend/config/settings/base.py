"""
Общие настройки для всех окружений. local.py и production.py импортируют
всё отсюда и переопределяют только то, что отличается по окружению.
"""

from datetime import timedelta
from pathlib import Path

import environ
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(str(env_file))

SECRET_KEY = env("DJANGO_SECRET_KEY", default="insecure-dev-key-change-me")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])

# Каждое доменное приложение регистрируется под своим доменным пакетом
# (domains.<домен>.<приложение>), а не по слоям — см. docs/adr/ и
# domains/README.md. label в apps.py каждого приложения короткий и уникальный,
# поэтому имена не конфликтуют между доменами.
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Нужен для TrigramExtension (baseline-миграция) и TrigramSimilarity —
    # быстрый частичный/нечувствительный к регистру поиск (ТЗ п. 4.1).
    "django.contrib.postgres",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "drf_spectacular",
    "rest_framework_simplejwt.token_blacklist",
]

DOMAIN_APPS = [
    # Люди — владелец домена: Анель.
    "domains.people.clients",
    # Расписание — владелец домена: Дарья.
    "domains.scheduling.schedule",
    "domains.scheduling.attendance",
    # Деньги — владелец домена: Bekzat.
    "domains.money.subscriptions",
    "domains.money.payments",
    # Платформа — общий фундамент, используется всеми доменами.
    "domains.platform.core",
    "domains.platform.tenants",
    "domains.platform.users",
    "domains.platform.notifications",
    "domains.platform.tasks",
    "domains.platform.leads",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + DOMAIN_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "domains.platform.core.middleware.TenantMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Шаблоны организованы по доменам (см. domains/README.md) —
        # backend/templates/<домен>/..., а не общий шаблон-суп.
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                # Каркас: филиалы для переключателя + права для скрытия
                # пунктов меню — доступны во всех шаблонах.
                "domains.platform.core.context_processors.branches",
                "domains.platform.core.context_processors.user_permissions",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://kidscrm:kidscrm@localhost:5432/kidscrm"),
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Интерфейс на русском с первого дня; казахский — бэклог (ТЗ п. 10.1).
LANGUAGE_CODE = "ru"
TIME_ZONE = "Asia/Almaty"
USE_I18N = True
USE_TZ = True
LOCALE_PATHS = [BASE_DIR / "locale"]

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Кастомная модель пользователя заведена до первой миграции — переезжать
# с auth.User задним числом на реальных данных было бы намного дороже.
AUTH_USER_MODEL = "users.User"

# Сессия для страниц (не JWT — тот только для API, см.
# domains/platform/core/decorators.py).
LOGIN_URL = "core:login"
LOGIN_REDIRECT_URL = "core:home"
LOGOUT_REDIRECT_URL = "core:login"

REST_FRAMEWORK = {
    "DEFAULT_VERSIONING_CLASS": "rest_framework.versioning.URLPathVersioning",
    "DEFAULT_VERSION": "v1",
    "ALLOWED_VERSIONS": ["v1"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "PAGE_SIZE": 50,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "KidsCRM API",
    "DESCRIPTION": "REST API платформы KidsCRM (см. ADR-002 — версионирование через /api/v1/).",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "TOKEN_OBTAIN_SERIALIZER": "domains.platform.users.serializers.CustomTokenObtainSerializer",
}

# Celery — фоновые задачи (генерация занятий, автозадачи, пересчёты), ADR-002.
CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

CELERY_BEAT_SCHEDULE = {
    "reconcile-subscription-balances": {
        "task": "domains.money.subscriptions.tasks.reconcile_balances_task",
        "schedule": crontab(hour=3, minute=0),  # ночью, вне часов работы центра
    },
}
