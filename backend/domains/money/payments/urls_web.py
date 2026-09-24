from django.urls import path

from . import web_views

app_name = "payments_web"

urlpatterns = [
    path("child/<uuid:child_id>/tab/", web_views.child_payments_tab, name="child-tab-payments"),
    path("child/<uuid:child_id>/record/", web_views.record_payment_view, name="record-payment"),
]
