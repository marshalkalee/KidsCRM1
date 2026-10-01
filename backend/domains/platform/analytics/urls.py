from django.urls import path

from . import views

urlpatterns = [
    path("metrics/", views.metrics_api, name="analytics-metrics"),
    path("breakdown/", views.breakdown_api, name="analytics-breakdown"),
    path("heatmap/", views.heatmap_api, name="analytics-heatmap"),
    path("group-occupancy/", views.group_occupancy_api, name="analytics-group-occupancy"),
    path("funnel/", views.funnel_api, name="analytics-funnel"),
    path("funnel/by/", views.funnel_by_api, name="analytics-funnel-by"),
    path("rejections/", views.rejections_api, name="analytics-rejections"),
    path("rejections/by/", views.rejections_by_api, name="analytics-rejections-by"),
    path("branches/", views.branches_api, name="analytics-branches"),
    path("branches/trend/", views.branch_trends_api, name="analytics-branch-trends"),
    path("sources/", views.sources_api, name="analytics-sources"),
    path("export/", views.export_api, name="analytics-export"),
    path("catalog/", views.catalog_api, name="analytics-catalog"),
]
