from django.urls import path

from . import public_views

app_name = "public_leads"

urlpatterns = [
    path("<str:public_key>/", public_views.PublicLeadCreateView.as_view(), name="create"),
]
