"""Настройки для локальной разработки."""

from .base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Без manifest-хранилища в деве — иначе {% static %} требует collectstatic
# перед каждым запуском runserver. **STORAGES (не полная замена словаря) —
# иначе "default" из base.py потерялся бы и default_storage/ImageField
# упали бы с InvalidStorageError (см. base.py).
STORAGES = {
    **STORAGES,  # noqa: F405
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
}
