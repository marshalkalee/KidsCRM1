from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "tenants"

router = DefaultRouter()
router.register("branches", views.BranchViewSet, basename="branch")
router.register("rooms", views.RoomViewSet, basename="room")

urlpatterns = [
    path("organization/", views.OrganizationMeView.as_view(), name="organization-me"),
    *router.urls,
]
