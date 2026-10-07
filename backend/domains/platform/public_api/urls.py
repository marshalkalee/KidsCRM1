"""Публичное API v1: /api/public/v1/ (TRU-176, docs/public-api.md).

Схема OpenAPI и документация строятся из этих маршрутов — руками не пишутся."""

from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView

from . import views

app_name = "public_api"

# Маршруты с данными — обязательство v1; их же видит схема OpenAPI.
data_patterns = [
    path("children/", views.ChildList.as_view(), name="children"),
    path("groups/", views.GroupList.as_view(), name="groups"),
    path("lessons/", views.LessonList.as_view(), name="lessons"),
    path("attendance/", views.AttendanceList.as_view(), name="attendance"),
    path("subscriptions/", views.SubscriptionList.as_view(), name="subscriptions"),
    path("payments/", views.PaymentList.as_view(), name="payments"),
    path("leads/", views.LeadCreate.as_view(), name="leads"),
]

urlpatterns = [
    *data_patterns,
    # Документация — без ключа: в ней нет данных, только контракт.
    path(
        "schema/",
        SpectacularAPIView.as_view(
            urlconf="domains.platform.public_api.schema_urls",
            custom_settings={
                "TITLE": "KidsCRM — публичное API v1",
                "DESCRIPTION": (
                    "Тариф Enterprise. Ключ: заголовок `Authorization: Bearer kc_live_…`. "
                    "Лимиты: 60 запросов в минуту и 20 000 в сутки на ключ, 429 с "
                    "`Retry-After`. Правила совместимости — docs/public-api.md."
                ),
                "VERSION": "1.0.0",
            },
        ),
        name="schema",
    ),
    path("docs/", SpectacularRedocView.as_view(url_name="public_api:schema"), name="docs"),
]
