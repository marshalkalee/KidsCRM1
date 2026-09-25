from django.urls import path
from rest_framework.routers import DefaultRouter

from . import import_api_views, views

app_name = "clients"

router = DefaultRouter()
router.register("children", views.ChildViewSet, basename="child")
router.register("parents", views.ParentContactViewSet, basename="parent-contact")
router.register("child-contacts", views.ChildContactViewSet, basename="child-contact")
router.register("communications", views.CommunicationLogViewSet, basename="communication-log")

urlpatterns = [
    path("search/", views.global_search_api, name="global-search"),
    # До router.urls: иначе "table" поймает children/<pk>/.
    path("children/table/", views.child_table_api, name="child-table"),
    path("children/photo/", views.child_photo_api, name="child-photo"),
    # Импорт (для frontend2) — тот же жизненный цикл, что у веб-экранов.
    path("children/import/analyze/", import_api_views.import_analyze, name="import-analyze"),
    path("children/import/preview/", import_api_views.import_preview, name="import-preview"),
    path("children/import/jobs/", import_api_views.import_jobs_list, name="import-jobs"),
    path("children/import/confirm/", import_api_views.import_confirm, name="import-confirm"),
    path(
        "children/import/jobs/<uuid:job_id>/",
        import_api_views.import_job_detail,
        name="import-job-detail",
    ),
    path(
        "children/import/jobs/<uuid:job_id>/decisions/",
        import_api_views.import_decisions,
        name="import-decisions",
    ),
    path(
        "children/import/jobs/<uuid:job_id>/report.xlsx",
        import_api_views.import_report,
        name="import-report",
    ),
    path(
        "children/import/jobs/<uuid:job_id>/rollback/",
        import_api_views.import_rollback,
        name="import-rollback",
    ),
    *router.urls,
]
