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
    "anymail",
]

DOMAIN_APPS = [
    # Люди — владелец домена: Анель.
    "domains.people.clients",
    "domains.people.portal",
    # Расписание — владелец домена: Дарья.
    "domains.scheduling.schedule",
    "domains.scheduling.groups",
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
    "domains.platform.ai",
    "domains.platform.analytics",
    "domains.scheduling.schedule_templates",
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
        # Своих шаблонов нет (веб — frontend2, TRU-88): только админка Django.
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
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
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    # Django требует явный "default" в STORAGES, если этот словарь вообще
    # переопределён (иначе default_storage/FileField падают с
    # InvalidStorageError) — раньше здесь был только "staticfiles", потому
    # что до фото ребёнка загрузки файлов в проекте не было.
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Загружаемые пользователями файлы (фото ребёнка и т.п.) — локальный диск,
# не облачное хранилище: backend/media уже в .gitignore и живёт в том же
# bind-mount volume, что и код (docker-compose.yml: ./backend:/app), поэтому
# сохраняется между перезапусками контейнера без отдельного volume. Если
# понадобится S3-совместимое хранилище (несколько инстансов backend без
# общего диска) — единственное, что меняется, это STORAGES["default"], сама
# модель/форма не завязаны на способ хранения.
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Кастомная модель пользователя заведена до первой миграции — переезжать
# с auth.User задним числом на реальных данных было бы намного дороже.
AUTH_USER_MODEL = "users.User"

# Сессия для страниц (не JWT — тот только для API, см.
# domains/platform/core/decorators.py).
LOGOUT_REDIRECT_URL = "core:login"

REST_FRAMEWORK = {
    "DEFAULT_VERSIONING_CLASS": "rest_framework.versioning.URLPathVersioning",
    "DEFAULT_VERSION": "v1",
    "ALLOWED_VERSIONS": ["v1"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "public_lead_ip": "10/hour",
        "public_lead_org": "100/hour",
    },
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
    # Legacy users created before Argon2 was enabled still have PBKDF2 hashes.
    # Keep the hasher available for verification; Django upgrades the hash to
    # the first hasher (Argon2) after their next successful login.
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
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

# "default" — как у Django по умолчанию (LocMem), чтобы не менять поведение
# того, что уже на нём живёт (троттлинг и т.п.). "import_progress" — общий
# для веба и воркера (Redis): прогресс импорта нельзя писать в ImportJob,
# пока импорт идёт одной транзакцией — снаружи этих записей не видно
# (domains/people/clients/progress.py).
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "import_progress": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL", default="redis://localhost:6379/0"),
        "KEY_PREFIX": "import_progress",
    },
    # Аналитика (TRU-118, ADR-0006): общий для всех воркеров кэш готовых
    # метрик — locmem у каждого процесса свой, и дашборд считался бы заново
    # в каждом воркере.
    "analytics": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL", default="redis://localhost:6379/0"),
        "KEY_PREFIX": "analytics",
    },
}

CELERY_BEAT_SCHEDULE = {
    # Снимки долга и заполняемости для истории (TRU-118, ADR-0006): каждый
    # час на сегодняшнюю дату центра, последний за день перезаписывает.
    "snapshot-analytics-metrics": {
        "task": "domains.platform.analytics.tasks.snapshot_metrics_task",
        "schedule": crontab(minute=50),
    },
    "generate-lessons-daily": {
        "task": (
            "domains.scheduling.schedule_templates.tasks"
            ".generate_lessons_for_all_active_templates"
        ),
        "schedule": crontab(hour=3, minute=0),
    },
    "reconcile-subscription-balances": {
        "task": "domains.money.subscriptions.tasks.reconcile_balances_task",
        "schedule": crontab(hour=3, minute=0),
    },
    # Заявки-продления по заканчивающимся абонементам (TRU-98) — после
    # пересчёта статусов, чтобы список «заканчивается» был свежим.
    "create-renewal-leads": {
        "task": "domains.money.subscriptions.tasks.create_renewal_leads_task",
        "schedule": crontab(hour=1, minute=0),
    },
    "update-subscription-statuses": {
        "task": "domains.money.subscriptions.tasks.update_subscription_statuses_task",
        "schedule": crontab(hour=0, minute=5),  # сразу после полуночи — "утром уже истёк"
    },
    "create-lead-stale-tasks": {
        "task": "domains.platform.tasks.tasks.create_lead_stale_tasks_task",
        "schedule": crontab(hour=2, minute=0),
    },
    "create-debt-reminder-tasks": {
        "task": "domains.platform.tasks.tasks.create_debt_reminder_tasks_task",
        "schedule": crontab(hour=2, minute=15),
    },
    # Еженедельный дайджест ИИ (TRU-163): раз в час проверяем, у каких центров
    # наступили их день и час по местному времени.
    "dispatch-ai-digests": {
        "task": "domains.platform.ai.tasks.dispatch_ai_digests",
        "schedule": crontab(minute=10),
    },
}

# ИИ-помощник (эксперимент): без ключа функции выключены, экраны их не показывают.
# Ключ — только из окружения, в коде и репозитории его нет.
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")
AI_MODEL = env("AI_MODEL", default="claude-opus-5")
# Провайдер: anthropic (по умолчанию) или openai — для показа с ключом OpenAI.
AI_PROVIDER = env("AI_PROVIDER", default="anthropic")
OPENAI_API_KEY = env("OPENAI_API_KEY", default="")
OPENAI_MODEL = env("OPENAI_MODEL", default="gpt-4o-mini")
OPENAI_VISION_MODEL = env("OPENAI_VISION_MODEL", default="gpt-4o")
# Чат на главной: инструментов много, вопросы свободные — mini путается в
# цепочках вызовов, поэтому модель сильнее, чем для коротких задач.
OPENAI_CHAT_MODEL = env("OPENAI_CHAT_MODEL", default="gpt-4o")
# Еженедельные рекомендации: сильная модель, вызов только из Celery.
OPENAI_DIGEST_MODEL = env("OPENAI_DIGEST_MODEL", default="gpt-5.4")
# В production без ключа ИИ скрыт. local.py включает детерминированную
# фикстуру, чтобы разработка и демо не зависели от внешнего API.
AI_FIXTURE_MODE = env.bool("AI_FIXTURE_MODE", default=False)
AI_GENERATION_MAX_INPUT_CHARS = env.int("AI_GENERATION_MAX_INPUT_CHARS", default=120_000)

# Учёт расхода ИИ (TRU-160, ADR-0009 раздел 5). Цены — $ за 1 млн токенов
# (вход, выход), октябрь 2026. Модель без цены считается по нулям и пишется
# в лог: расход в токенах всё равно учтён, дописать цену и пересчитать.
AI_PRICES_USD = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-5.4": (2.50, 15.00),
    "gpt-5.4-mini": (0.75, 4.50),
    "claude-sonnet-5-5": (2.00, 10.00),
}
# Курс только для показа в тенге: учёт ведётся в $, как выставляет провайдер.
AI_USD_KZT = env.float("AI_USD_KZT", default=500.0)
# Лимит месяца на центр, ₸, если у организации свой не задан (ai_monthly_limit_kzt).
AI_MONTHLY_LIMIT_KZT = env.int("AI_MONTHLY_LIMIT_KZT", default=10_000)

# Код входа родителя (ADR-0007, otp/senders.py): каналы по порядку, через
# запятую — первый не доставил, пробуем следующий. console — код в лог.
OTP_CHANNELS = env("OTP_CHANNELS", default="console")
OTP_CODE_TTL_SECONDS = env.int("OTP_CODE_TTL_SECONDS", default=300)
OTP_TELEGRAM_TOKEN = env("OTP_TELEGRAM_TOKEN", default="")
OTP_MOBIZON_API_KEY = env("OTP_MOBIZON_API_KEY", default="")
OTP_MOBIZON_SENDER = env("OTP_MOBIZON_SENDER", default="")

# Центр рассылок (TRU-168): сообщения родителям — только через
# domains.platform.notifications.messaging. Email — через django-anymail:
# провайдер (Amazon SES, Unisender Go, Mailgun…) меняется в .env, недоставка
# и жалобы приходят одинаково на вебхук anymail/<esp>/tracking/.
# Без EMAIL_ESP письма пишутся в лог (как OTP-канал console).
EMAIL_ESP = env("EMAIL_ESP", default="")
if EMAIL_ESP:
    EMAIL_BACKEND = f"anymail.backends.{EMAIL_ESP}.EmailBackend"
    ANYMAIL = {
        key: value
        for key, value in {
            "AMAZON_SES_CLIENT_PARAMS": {"region_name": env("AWS_REGION", default="eu-central-1")},
            "UNISENDER_GO_API_KEY": env("UNISENDER_GO_API_KEY", default=""),
            "MAILGUN_API_KEY": env("MAILGUN_API_KEY", default=""),
            "WEBHOOK_SECRET": env("ANYMAIL_WEBHOOK_SECRET", default=""),
        }.items()
        if value
    }
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
# Адрес отправителя — домен платформы; имя — название центра, ответ — на
# адрес центра (настройка рассылок). Свой домен у каждого центра — это DNS
# (SPF, DKIM) на центр, на старте не нужно.
MESSAGING_FROM_EMAIL = env("MESSAGING_FROM_EMAIL", default="noreply@kidscrm.kz")
# Публичный адрес сайта — для ссылки «отписаться» в письме.
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", default="http://localhost")
