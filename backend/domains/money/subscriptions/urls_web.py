from django.urls import path

from . import debtors_web_views as views
from . import renewals_web_views

app_name = "subscriptions_web"

urlpatterns = [
    path("debtors/", views.debtors_page, name="debtors-page"),
    path("debtors/data/", views.debtors_data, name="debtors-data"),
    path("debtors/export/", views.export_debtors, name="debtors-export"),
    path(
        "debtors/<uuid:subscription_id>/remind/",
        views.create_reminder_task_view,
        name="debtors-remind",
    ),
    path("renewals/", renewals_web_views.renewals_page, name="renewals-page"),
    path("renewals/data/", renewals_web_views.renewals_data, name="renewals-data"),
    path(
        "renewals/<uuid:subscription_id>/contacted/",
        renewals_web_views.mark_contacted_view,
        name="renewals-contacted",
    ),
    path(
        "renewals/<uuid:subscription_id>/sell/",
        renewals_web_views.sell_renewal_view,
        name="renewals-sell",
    ),
]
