from django.urls import path

from . import views

app_name = "ai"

urlpatterns = [
    path("status/", views.ai_status, name="status"),
    path("lead-from-text/", views.lead_from_text, name="lead-from-text"),
    path("leads/<uuid:lead_id>/message/", views.lead_message, name="lead-message"),
]
