from django.apps import AppConfig


class LeadsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "domains.platform.leads"
    label = "leads"

    def ready(self):
        from . import signals  # noqa: F401 — справочники по умолчанию у новой организации
