from decimal import Decimal

from django.db.models import DecimalField, Q, Sum
from django.db.models.functions import Coalesce
from rest_framework import viewsets

from domains.money.payments.models import Payment
from domains.platform.core.permissions import IsNotTeacher

from .models import Subscription
from .serializers import SubscriptionSerializer


class SubscriptionViewSet(viewsets.ReadOnlyModelViewSet):
    """История абонементов для карточки ребёнка во frontend2."""

    serializer_class = SubscriptionSerializer
    permission_classes = [IsNotTeacher]

    def get_queryset(self):
        confirmed_payments = Q(
            payments__status=Payment.Status.CONFIRMED,
            payments__deleted_at__isnull=True,
        )
        queryset = (
            Subscription.objects.for_tenant(self.request.user.organization)
            .select_related("child", "subscription_type_version", "direction", "branch")
            .annotate(
                paid=Coalesce(
                    Sum("payments__amount", filter=confirmed_payments),
                    Decimal("0"),
                    output_field=DecimalField(max_digits=12, decimal_places=0),
                )
            )
            .order_by("-starts_on", "-created_at")
        )
        child_id = self.request.query_params.get("child_id")
        if child_id:
            queryset = queryset.filter(child_id=child_id)
        return queryset
