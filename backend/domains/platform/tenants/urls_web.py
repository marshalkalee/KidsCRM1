"""
Веб-маршруты (серверный рендеринг) — отдельно от urls.py (тот подключает
DRF-роутер под /api/v1/, см. config/urls.py). Тот же принцип разделения,
что и в web_views.py/views.py.
"""

from django.urls import path

from . import web_views

app_name = "tenants_web"

urlpatterns = [
    path("settings/organization/", web_views.organization_settings, name="organization-settings"),
    path("settings/branches/", web_views.branch_list, name="branch-list"),
    path("settings/branches/create/", web_views.branch_create, name="branch-create"),
    path("settings/branches/<uuid:pk>/edit/", web_views.branch_edit, name="branch-edit"),
    path("settings/branches/<uuid:pk>/archive/", web_views.branch_archive, name="branch-archive"),
    path("settings/branches/<uuid:branch_pk>/rooms/", web_views.room_list, name="room-list"),
    path(
        "settings/branches/<uuid:branch_pk>/rooms/create/",
        web_views.room_create,
        name="room-create",
    ),
    path(
        "settings/branches/<uuid:branch_pk>/rooms/<uuid:pk>/edit/",
        web_views.room_edit,
        name="room-edit",
    ),
    path(
        "settings/branches/<uuid:branch_pk>/rooms/<uuid:pk>/delete/",
        web_views.room_delete,
        name="room-delete",
    ),
    path("settings/directions/", web_views.direction_list, name="direction-list"),
    path("settings/directions/create/", web_views.direction_create, name="direction-create"),
    path("settings/directions/<uuid:pk>/edit/", web_views.direction_edit, name="direction-edit"),
    path(
        "settings/directions/<uuid:pk>/archive/",
        web_views.direction_archive,
        name="direction-archive",
    ),
]
