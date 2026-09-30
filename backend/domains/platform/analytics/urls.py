from django.urls import path

from . import views

urlpatterns = [
    path("metrics/", views.metrics_api, name="analytics-metrics"),
    path("breakdown/", views.breakdown_api, name="analytics-breakdown"),
    path("heatmap/", views.heatmap_api, name="analytics-heatmap"),
    path("catalog/", views.catalog_api, name="analytics-catalog"),
]
