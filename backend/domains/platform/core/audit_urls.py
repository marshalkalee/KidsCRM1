from django.urls import path

from .audit_views import AuditLogView

urlpatterns = [
    path("", AuditLogView.as_view(), name="audit-log"),
]
