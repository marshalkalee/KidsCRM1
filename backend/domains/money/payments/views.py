from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from domains.platform.core.permissions import IsNotTeacher, IsOwnerOrManagerOrAdmin

from .models import Payment
from .serializers import PaymentSerializer
from .services import cancel_payment, record_payment


class PaymentViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = PaymentSerializer

    def get_permissions(self):
        if self.action in ("create", "cancel"):
            return [IsOwnerOrManagerOrAdmin()]
        return [IsNotTeacher()]

    def get_queryset(self):
        # all_with_deleted() намеренно — отменённые оплаты обязаны быть видны в истории
        qs = Payment.objects.all_with_deleted().filter(organization=self.request.user.organization)
        subscription_id = self.request.query_params.get("subscription_id")
        child_id = self.request.query_params.get("child_id")
        parent_id = self.request.query_params.get("parent_id")
        if subscription_id:
            qs = qs.filter(subscription_id=subscription_id)
        if child_id:
            qs = qs.filter(subscription__child_id=child_id)
        if parent_id:
            qs = qs.filter(subscription__child__contacts__id=parent_id)
        return qs.select_related("subscription", "received_by").distinct()

    def perform_create(self, serializer):
        payment = record_payment(
            actor=self.request.user,
            subscription=serializer.validated_data["subscription"],
            amount=serializer.validated_data["amount"],
            method=serializer.validated_data["method"],
            comment=serializer.validated_data.get("comment", ""),
        )
        serializer.instance = payment

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        payment = self.get_object()
        reason = request.data.get("reason", "")
        if not reason:
            return Response({"detail": "Укажите причину отмены"}, status=400)
        cancel_payment(payment, actor=request.user, reason=reason)
        return Response(PaymentSerializer(payment).data)
