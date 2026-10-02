from django.urls import path

from . import views

app_name = "core"

# Веб — только frontend2 (React, ADR-004); серверные страницы удалены в
# TRU-88. Здесь остаётся проверка живости для мониторинга.
urlpatterns = [
    path("healthz/", views.healthz, name="healthz"),
]
