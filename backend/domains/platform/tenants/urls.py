from django.urls import path
from rest_framework.routers import DefaultRouter

from . import onboarding_api, views

app_name = "tenants"

router = DefaultRouter()
router.register("branches", views.BranchViewSet, basename="branch")
router.register("rooms", views.RoomViewSet, basename="room")
router.register("directions", views.DirectionViewSet, basename="direction")

urlpatterns = [
    path("organization/", views.OrganizationMeView.as_view(), name="organization-me"),
    path("onboarding/", onboarding_api.onboarding_state, name="onboarding"),
    path(
        "onboarding/organization/confirm/",
        onboarding_api.onboarding_confirm_organization,
        name="onboarding-confirm-organization",
    ),
    path("onboarding/finish/", onboarding_api.onboarding_finish, name="onboarding-finish"),
    path("onboarding/<str:step>/skip/", onboarding_api.onboarding_skip, name="onboarding-skip"),
    path(
        "organization/settings/",
        views.organization_settings,
        name="organization-settings",
    ),
    *router.urls,
]
