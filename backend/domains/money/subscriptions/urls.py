from django.urls import path
from rest_framework.routers import DefaultRouter

from . import lists_api, views

app_name = "subscriptions"

router = DefaultRouter()
router.register("subscription-types", views.SubscriptionTypeViewSet, basename="subscription-type")
router.register("", views.SubscriptionViewSet, basename="subscription")


# Раньше роутера: иначе «debtors» примется за id абонемента.
urlpatterns = [
    path("debtors/", lists_api.debtors_api, name="api-debtors"),
    path("debtors/export/", lists_api.debtors_export_api, name="api-debtors-export"),
    path("renewals/", lists_api.renewals_api, name="api-renewals"),
    path(
        "renewals/<uuid:subscription_id>/contacted/",
        lists_api.renewal_contacted_api,
        name="api-renewal-contacted",
    ),
    *router.urls,
]
