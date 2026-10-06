from rest_framework.routers import DefaultRouter

from .staff_requests import ParentRequestViewSet

app_name = "parent_requests"

router = DefaultRouter()
router.register("", ParentRequestViewSet, basename="parent-request")

urlpatterns = router.urls
