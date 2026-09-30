from django.urls import path

from . import views

urlpatterns = [
    path("metrics/", views.metrics_api, name="analytics-metrics"),
    path("catalog/", views.catalog_api, name="analytics-catalog"),
]
