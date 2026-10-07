from django.apps import AppConfig


class PublicApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "domains.platform.public_api"
    label = "public_api"
