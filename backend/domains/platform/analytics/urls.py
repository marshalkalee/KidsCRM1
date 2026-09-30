from django.urls import path

from . import views

urlpatterns = [
    path("metrics/", views.metrics_api, name="analytics-metrics"),
    path("breakdown/", views.breakdown_api, name="analytics-breakdown"),
    path("heatmap/", views.heatmap_api, name="analytics-heatmap"),
    path("funnel/", views.funnel_api, name="analytics-funnel"),
    path("funnel/by/", views.funnel_by_api, name="analytics-funnel-by"),
    path("funnel/export/", views.funnel_export_api, name="analytics-funnel-export"),
    path("catalog/", views.catalog_api, name="analytics-catalog"),
]
