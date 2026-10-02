from django.apps import AppConfig


class PortalConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "domains.people.portal"
    label = "portal"
    verbose_name = "Кабинет родителя"
