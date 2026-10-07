from django.urls import path

from . import views

app_name = "ai"

urlpatterns = [
    path("status/", views.ai_status, name="status"),
    path("recommendations/groups/", views.group_recommendations, name="group-recommendations"),
    path(
        "recommendations/<uuid:recommendation_id>/dismiss/",
        views.dismiss_recommendation,
        name="dismiss-recommendation",
    ),
    path("content/", views.content_studio, name="content-studio"),
    path(
        "content/<uuid:generation_id>/cancel/",
        views.cancel_content_generation,
        name="content-generation-cancel",
    ),
    path("content/drafts/", views.content_drafts, name="content-drafts"),
    path(
        "content/drafts/<uuid:draft_id>/",
        views.content_draft_detail,
        name="content-draft-detail",
    ),
    path("chat/", views.chat_view, name="chat"),
    path("conversations/", views.conversations, name="conversations"),
    path(
        "conversations/<uuid:conversation_id>/",
        views.conversation_detail,
        name="conversation-detail",
    ),
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
