from django.urls import path

from . import views

app_name = "ai"

urlpatterns = [
    path("status/", views.ai_status, name="status"),
    path("chat/", views.chat_view, name="chat"),
    path("lead-from-text/", views.lead_from_text, name="lead-from-text"),
    path("leads/<uuid:lead_id>/message/", views.lead_message, name="lead-message"),
    path("search/", views.search, name="search"),
    path("attendance-photo/", views.attendance_from_photo, name="attendance-photo"),
    path("import-clean/", views.import_clean, name="import-clean"),
    path("reminders/", views.reminders, name="reminders"),
    path("communication-note/", views.communication_note, name="communication-note"),
    path("children/<uuid:child_id>/brief/", views.child_brief, name="child-brief"),
    path("leads/<uuid:lead_id>/groups/", views.lead_groups, name="lead-groups"),
    path("daily-plan/", views.daily_plan, name="daily-plan"),
    path("rejection-reason/", views.rejection_reason, name="rejection-reason"),
]
