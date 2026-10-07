"""Только маршруты с данными — для схемы OpenAPI публичного API."""

from django.urls import include, path

from .urls import data_patterns

urlpatterns = [path("api/public/v1/", include(data_patterns))]
