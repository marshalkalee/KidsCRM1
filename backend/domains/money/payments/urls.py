from rest_framework.routers import DefaultRouter

from . import views

app_name = "payments"

router = DefaultRouter()
router.register("", views.PaymentViewSet, basename="payment")

urlpatterns = router.urls
