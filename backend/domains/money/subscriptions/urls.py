from rest_framework.routers import DefaultRouter

from . import views

app_name = "subscriptions"

router = DefaultRouter()
router.register("", views.SubscriptionViewSet, basename="subscription")

urlpatterns = router.urls
