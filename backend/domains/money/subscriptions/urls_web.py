from django.urls import path

from . import debtors_web_views as views

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
]
