from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.notifications, name="list"),
    path("seen/", views.mark_seen, name="seen"),
]
