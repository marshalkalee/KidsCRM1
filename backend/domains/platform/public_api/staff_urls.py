from django.urls import path

from . import staff_views

app_name = "api_keys"

urlpatterns = [
    path("", staff_views.keys, name="list"),
    path("<uuid:key_id>/revoke/", staff_views.revoke, name="revoke"),
    path("log/", staff_views.request_log, name="log"),
]
