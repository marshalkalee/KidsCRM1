from rest_framework.routers import DefaultRouter

from .views import CommunicationLogViewSet

router = DefaultRouter()
router.register("", CommunicationLogViewSet, basename="communication-log")

urlpatterns = router.urls
