import uuid

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

    def create(self, request, *args, **kwargs):
        from domains.money.subscriptions.debt import debt_by_child, subscription_debt

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            payment = record_payment(
                actor=request.user,
                subscription=data["subscription"],
                amount=data["amount"],
                method=data["method"],
                comment=data.get("comment", ""),
                idempotency_key=data.get("idempotency_key"),
            )
        except (ValueError, ArithmeticError) as exc:
            return Response({"detail": str(exc) or "Некорректная сумма"}, status=400)
        subscription = payment.subscription
        result = PaymentSerializer(payment, context=self.get_serializer_context()).data
        # Экрану — итог сразу: что осталось по абонементу и по ребёнку.
        result["subscription_debt"] = str(subscription_debt(subscription))
        result["child_debt"] = str(
            debt_by_child(request.user.organization, [subscription.child_id]).get(
                subscription.child_id, 0
            )
        )
        return Response(result, status=201)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        payment = self.get_object()
        reason = request.data.get("reason", "")
        if not reason:
            return Response({"detail": "Укажите причину отмены"}, status=400)
        cancel_payment(payment, actor=request.user, reason=reason)
        return Response(PaymentSerializer(payment).data)

    @action(detail=False, methods=["get"])
    def child_debt(self, request):
        from domains.money.subscriptions.debt import debt_by_child

        child_id = request.query_params.get("child_id")
        if not child_id:
            return Response({"detail": "child_id обязателен"}, status=400)
        debts = debt_by_child(request.user.organization, [child_id])
        return Response({"debt": str(debts.get(uuid.UUID(child_id), 0))})
