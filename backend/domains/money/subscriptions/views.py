"""API для вкладок «Абонементы»/«Оплаты» карточки ребёнка (TRU-70,
frontend2), см. docs/contracts.md §6."""

from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from domains.people.clients.models import Child
from domains.platform.core.permissions import IsNotTeacher
from domains.platform.tenants.models import Branch, Direction

from .freezes import freeze_subscription, unfreeze_subscription
from .models import Subscription
from .renewals import sell_renewal
from .sales import sell_subscription
from .serializers import (
    SubscriptionFreezeSerializer,
    SubscriptionLedgerEntrySerializer,
    SubscriptionSerializer,
)
from .subscription_types import get_selectable_subscription_types


class SubscriptionViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    serializer_class = SubscriptionSerializer
    permission_classes = [IsNotTeacher]

    def get_queryset(self):
        qs = Subscription.objects.for_tenant(self.request.user.organization).select_related(
            "subscription_type_version",
            "direction",
            "branch",
        )
        child_id = self.request.query_params.get("child_id")
        if child_id:
            qs = qs.filter(child_id=child_id)
        return qs.order_by("-starts_on")

    @action(detail=True, methods=["get"])
    def ledger(self, request, pk=None):
        subscription = self.get_object()
        entries = subscription.ledger_entries.order_by("-created_at")
        return Response(SubscriptionLedgerEntrySerializer(entries, many=True).data)

    @action(detail=True, methods=["get"])
    def freezes(self, request, pk=None):
        subscription = self.get_object()
        return Response(SubscriptionFreezeSerializer(subscription.freezes.all(), many=True).data)

    @action(detail=True, methods=["post"])
    def freeze(self, request, pk=None):
        subscription = self.get_object()
        freeze_subscription(
            subscription,
            actor=request.user,
            starts_on=request.data["starts_on"],
            ends_on=request.data["ends_on"],
            reason=request.data.get("reason", ""),
        )
        return Response(SubscriptionSerializer(subscription).data)

    @action(detail=True, methods=["post"])
    def unfreeze(self, request, pk=None):
        subscription = self.get_object()
        unfreeze_subscription(
            subscription, actor=request.user, actual_end_date=request.data.get("actual_end_date")
        )
        return Response(SubscriptionSerializer(subscription).data)

    @action(detail=True, methods=["post"])
    def renew(self, request, pk=None):
        old = self.get_object()
        subscription_type = get_selectable_subscription_types(
            old.organization, branch=old.branch
        ).get(
            pk=request.data["subscription_type_id"],
        )
        new_sub, _payment = sell_renewal(
            old,
            actor=request.user,
            child=old.child,
            subscription_type_version=subscription_type.versions.latest(),
            direction=old.direction,
            branch=old.branch,
            starts_on=request.data["starts_on"],
            ends_on=request.data["ends_on"],
            discount_amount=request.data.get("discount_amount", 0),
            discount_reason=request.data.get("discount_reason", ""),
            paid_amount=request.data["paid_amount"],
            payment_method=request.data["payment_method"],
        )
        return Response(SubscriptionSerializer(new_sub).data, status=201)

    @action(detail=False, methods=["post"])
    def sell(self, request):
        organization = request.user.organization
        child = Child.objects.for_tenant(organization).get(pk=request.data["child_id"])
        subscription_type = get_selectable_subscription_types(organization).get(
            pk=request.data["subscription_type_id"]
        )
        branch = Branch.objects.for_tenant(organization).get(pk=request.data["branch_id"])
        direction = Direction.objects.for_tenant(organization).get(pk=request.data["direction_id"])
        new_sub, _payment = sell_subscription(
            actor=request.user,
            child=child,
            subscription_type_version=subscription_type.versions.latest(),
            direction=direction,
            branch=branch,
            starts_on=request.data["starts_on"],
            ends_on=request.data["ends_on"],
            discount_amount=request.data.get("discount_amount", 0),
            discount_reason=request.data.get("discount_reason", ""),
            paid_amount=request.data["paid_amount"],
            payment_method=request.data["payment_method"],
        )
        return Response(SubscriptionSerializer(new_sub).data, status=201)
