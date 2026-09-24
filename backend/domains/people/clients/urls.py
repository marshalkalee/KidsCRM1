from django.urls import path
from rest_framework.routers import DefaultRouter

from . import import_api_views, views

app_name = "clients"

router = DefaultRouter()
router.register("children", views.ChildViewSet, basename="child")
router.register("parents", views.ParentContactViewSet, basename="parent-contact")
router.register("child-contacts", views.ChildContactViewSet, basename="child-contact")

urlpatterns = [
    path("search/", views.global_search_api, name="global-search"),
    # До router.urls: иначе "table" поймает children/<pk>/.
    path("children/table/", views.child_table_api, name="child-table"),
    # Импорт (для frontend2) — тот же жизненный цикл, что у веб-экранов.
    path("children/import/preview/", import_api_views.import_preview, name="import-preview"),
    path("children/import/confirm/", import_api_views.import_confirm, name="import-confirm"),
    path(
        "children/import/jobs/<uuid:job_id>/",
        import_api_views.import_job_detail,
        name="import-job-detail",
    ),
    path(
        "children/import/jobs/<uuid:job_id>/rollback/",
        import_api_views.import_rollback,
        name="import-rollback",
    ),
    *router.urls,
]
