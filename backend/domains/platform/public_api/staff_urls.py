from django.urls import path

from . import profile_views, staff_views

app_name = "api_keys"

urlpatterns = [
    path("", staff_views.keys, name="list"),
    path("<uuid:key_id>/revoke/", staff_views.revoke, name="revoke"),
    path("log/", staff_views.request_log, name="log"),
    # Публичный профиль центра (TRU-179).
    path("center-profile/", profile_views.center_profile, name="center-profile"),
    path("center-profile/logo/", profile_views.center_logo, name="center-logo"),
    path("center-profile/photos/", profile_views.center_photos, name="center-photos"),
]
