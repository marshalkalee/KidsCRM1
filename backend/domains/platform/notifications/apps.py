from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "domains.platform.notifications"
    label = "notifications"

    def ready(self):
        # Вебхуки почтового провайдера (anymail) → журнал рассылок и отписка.
        from .messaging import signals  # noqa: F401
