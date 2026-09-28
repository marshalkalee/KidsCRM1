from django.urls import path

from . import views

app_name = "ai"

urlpatterns = [
    path("status/", views.ai_status, name="status"),
    path("lead-from-text/", views.lead_from_text, name="lead-from-text"),
    path("leads/<uuid:lead_id>/message/", views.lead_message, name="lead-message"),
    path("search/", views.search, name="search"),
    path("attendance-photo/", views.attendance_from_photo, name="attendance-photo"),
    path("import-clean/", views.import_clean, name="import-clean"),
]
