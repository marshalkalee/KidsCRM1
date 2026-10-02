from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "payments"

router = DefaultRouter()
# requests/ — раньше пустого префикса: иначе "requests" примут за id оплаты.
router.register("requests", views.PaymentRequestViewSet, basename="payment-request")
router.register("", views.PaymentViewSet, basename="payment")

urlpatterns = [
    path("kaspi/webhook/", views.KaspiWebhookView.as_view(), name="kaspi-webhook"),
    path(
        "kaspi/test-pay/<str:external_id>/", views.FakeKaspiPayView.as_view(), name="kaspi-test-pay"
    ),
    *router.urls,
]
