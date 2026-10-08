import uuid

from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from domains.platform.core.permissions import CanViewClientMoney, IsOwnerOrManagerOrAdmin

from .models import Payment
from .serializers import PaymentSerializer
from .services import cancel_payment, record_payment


def _uuid_or_none(value):
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _debts(organization, subscription):
    """Экрану — итог сразу: что осталось по абонементу и по ребёнку."""
    from domains.money.subscriptions.debt import debt_by_child, subscription_debt

    return {
        "subscription_debt": str(subscription_debt(subscription)),
        "child_debt": str(
            debt_by_child(organization, [subscription.child_id]).get(subscription.child_id, 0)
        ),
    }


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
        return [CanViewClientMoney()]

    def get_queryset(self):
        # all_with_deleted() намеренно — отменённые оплаты обязаны быть видны в истории
        qs = Payment.objects.all_with_deleted().filter(organization=self.request.user.organization)
        lookups = {
            "subscription_id": "subscription_id",
            "child_id": "subscription__child_id",
            # parent_id — id родителя (ParentContact), а не связи ChildContact.
            "parent_id": "subscription__child__contacts__parent_contact_id",
        }
        for param, lookup in lookups.items():
            raw = self.request.query_params.get(param)
            if not raw:
                continue
            value = _uuid_or_none(raw)
            if value is None:
                # Мусор в фильтре — пустой список, а не 500 (TRU-131).
                return qs.none()
            conditions = {lookup: value}
            if param == "parent_id":
                # В одном filter() — та же связь: отвязанный родитель не видит оплат.
                conditions["subscription__child__contacts__deleted_at__isnull"] = True
            qs = qs.filter(**conditions)
        return qs.select_related("subscription", "received_by").distinct()

    def create(self, request, *args, **kwargs):
        from domains.people.clients.models import ChildContact

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        payer = data.get("payer")
        if payer is None:
            current_payer_link = ChildContact.objects.filter(
                child=data["subscription"].child,
                is_payer=True,
            ).first()
            payer = current_payer_link.parent_contact if current_payer_link else None

        try:
            payment = record_payment(
                actor=request.user,
                subscription=data["subscription"],
                amount=data["amount"],
                method=data["method"],
                payer=payer,
                comment=data.get("comment", ""),
                idempotency_key=data.get("idempotency_key"),
                paid_on=data.get("paid_on"),
            )
        except (ValueError, ArithmeticError) as exc:
            return Response({"detail": str(exc) or "Некорректная сумма"}, status=400)
        result = PaymentSerializer(payment, context=self.get_serializer_context()).data
        result.update(_debts(request.user.organization, payment.subscription))
        return Response(result, status=201)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        payment = self.get_object()
        reason = request.data.get("reason", "")
        if not reason:
            return Response({"detail": "Укажите причину отмены"}, status=400)
        try:
            cancel_payment(payment, actor=request.user, reason=reason)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(PaymentSerializer(payment).data)

    @action(detail=False, methods=["get"])
    def child_debt(self, request):
        from domains.money.subscriptions.debt import debt_by_child

        child_id = request.query_params.get("child_id")
        if not child_id:
            return Response({"detail": "child_id обязателен"}, status=400)
        debts = debt_by_child(request.user.organization, [child_id])
        return Response({"debt": str(debts.get(uuid.UUID(child_id), 0))})
