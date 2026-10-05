import uuid

from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from domains.platform.core.permissions import CanViewClientMoney, IsOwnerOrManagerOrAdmin
from domains.platform.tenants.org_settings import KASPI_PAYMENT_DETAILS, get_org_setting

from . import remote
from .kaspi import FakeKaspiGateway, GatewayError, GatewayEvent, WebhookRejected, get_gateway
from .models import Payment, PaymentRequest
from .serializers import PaymentRequestSerializer, PaymentSerializer
from .services import cancel_payment, record_payment


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


class PaymentRequestViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Счета на удалённую оплату Kaspi (payments/remote.py): выставить,
    подтвердить поступление, отменить. Права — как у приёма оплаты."""

    serializer_class = PaymentRequestSerializer

    def get_permissions(self):
        if self.action in ("create", "confirm", "cancel"):
            return [IsOwnerOrManagerOrAdmin()]
        return [CanViewClientMoney()]

    def get_queryset(self):
        qs = PaymentRequest.objects.for_tenant(self.request.user.organization)
        params = self.request.query_params
        if params.get("child_id"):
            qs = qs.filter(subscription__child_id=params["child_id"])
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        return qs.select_related(
            "subscription__child",
            "subscription__subscription_type_version",
            "parent_contact",
            "created_by",
        )

    def list(self, request, *args, **kwargs):
        remote.expire_stale(request.user.organization)
        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=["get"])
    def options(self, request):
        """Окну «Выставить счёт»: каким каналом уйдёт счёт, настроен ли он
        и чей телефон подставить."""
        organization = request.user.organization
        result = {
            **remote.channel_for(organization),
            "details": get_org_setting(organization, KASPI_PAYMENT_DETAILS),
            "phone": "",
            "parent_name": "",
        }
        child_id = request.query_params.get("child_id")
        if child_id:
            from domains.people.clients.models import Child

            child = get_object_or_404(Child.objects.for_tenant(organization), pk=child_id)
            parent, phone = remote.payer_contact(organization, child)
            result.update(phone=phone, parent_name=parent.full_name if parent else "")
        return Response(result)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            req = remote.create_request(
                actor=request.user,
                subscription=data["subscription"],
                amount=data["amount"],
                phone=data.get("phone", ""),
                idempotency_key=data.get("idempotency_key"),
                base_url=request.build_absolute_uri("/"),
            )
        except (ValueError, GatewayError) as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(self.get_serializer(req).data, status=201)

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        """«Оплата пришла»: администратор увидел поступление в Kaspi."""
        req = self.get_object()
        if req.status in (PaymentRequest.Status.CANCELLED, PaymentRequest.Status.FAILED):
            return Response(
                {"detail": "Счёт отменён — примите оплату обычным способом."}, status=400
            )
        req = remote.mark_paid(req, actor=request.user)
        result = self.get_serializer(req).data
        result.update(_debts(request.user.organization, req.subscription))
        return Response(result)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        try:
            req = remote.cancel_request(self.get_object(), actor=request.user)
        except (ValueError, GatewayError) as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(self.get_serializer(req).data)


class KaspiWebhookView(APIView):
    """Kaspi сообщает об оплате счёта. Без сессии и токена — подлинность
    проверяет шлюз по подписи. Неизвестный счёт — 200, чтобы не было
    бесконечных повторов."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        gateway = get_gateway()
        if gateway is None:
            raise Http404
        try:
            event = gateway.parse_webhook(request.body, request.headers)
        except WebhookRejected as exc:
            return Response({"detail": str(exc)}, status=403)
        req = remote.handle_event(event)
        return Response({"ok": True, "status": req.status if req else None})


class FakeKaspiPayView(APIView):
    """Тестовая страница оплаты счёта (только шлюз "fake", стенд):
    GET — что за счёт, POST — «оплатить», как это сделал бы Kaspi."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def _request(self, external_id):
        if not isinstance(get_gateway(), FakeKaspiGateway):
            raise Http404
        return get_object_or_404(
            PaymentRequest.objects.select_related(
                "organization",
                "subscription__child",
                "subscription__subscription_type_version",
            ),
            external_id=external_id,
        )

    def _payload(self, req):
        return {
            "organization": req.organization.name,
            "child_name": req.subscription.child.full_name,
            "subscription_name": req.subscription.subscription_type_version.name,
            "amount": str(req.amount),
            "phone": req.phone,
            "status": req.status,
        }

    def get(self, request, external_id):
        return Response(self._payload(self._request(external_id)))

    def post(self, request, external_id):
        req = self._request(external_id)
        if req.status != PaymentRequest.Status.PENDING:
            return Response(
                {"detail": "Счёт уже не ждёт оплаты.", **self._payload(req)}, status=400
            )
        req = remote.handle_event(
            GatewayEvent(
                external_id=external_id,
                status=GatewayEvent.PAID,
                transaction_id=f"{external_id}-tx",
            )
        )
        return Response(self._payload(req))
