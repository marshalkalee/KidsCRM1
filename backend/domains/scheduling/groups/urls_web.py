from django.urls import path

from . import web_views

app_name = "scheduling_web"

urlpatterns = [
    path("groups/", web_views.group_list, name="group-list"),
    path("groups/create/", web_views.group_create, name="group-create"),
    path("groups/<uuid:pk>/", web_views.group_detail, name="group-detail"),
    path("groups/<uuid:pk>/edit/", web_views.group_edit, name="group-edit"),
    path("groups/<uuid:pk>/close/", web_views.group_close, name="group-close"),
]
