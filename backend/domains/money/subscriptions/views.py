"""API для вкладок «Абонементы»/«Оплаты» карточки ребёнка (TRU-70,
frontend2), см. docs/contracts.md §6."""

from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from domains.people.clients.models import Child
from domains.platform.core.permissions import IsNotTeacher, IsOwnerOrManager
from domains.platform.core.utils import today_for_org
from domains.platform.tenants.models import Branch, Direction

from .debt import paid_sum
from .freezes import freeze_subscription, unfreeze_subscription
from .models import BalanceDiscrepancy, Subscription
from .reconciliation import manual_recompute
from .renewals import sell_renewal
from .sales import sell_subscription
from .serializers import (
    FreezeRequestSerializer,
    SaleRequestSerializer,
    SellRequestSerializer,
    SubscriptionFreezeSerializer,
    SubscriptionLedgerEntrySerializer,
    SubscriptionSerializer,
    UnfreezeRequestSerializer,
)
from .subscription_types import get_selectable_subscription_types


class SubscriptionViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    serializer_class = SubscriptionSerializer
    permission_classes = [IsNotTeacher]

    def get_queryset(self):
        qs = (
            Subscription.objects.for_tenant(self.request.user.organization)
            .select_related(
                "organization",
                "subscription_type_version",
                "direction",
                "branch",
            )
            .prefetch_related("freezes")
            .annotate(paid=paid_sum())
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

    @action(detail=True, methods=["post"])
    def recompute(self, request, pk=None):
        """Пересчитать остаток из журнала списаний (TRU-61) — при споре с родителем."""
        subscription = self.get_object()
        before = subscription.sessions_remaining_cache
        after = manual_recompute(subscription)
        return Response(
            {
                "before": before,
                "after": after,
                "fixed": before != after,
                "subscription": SubscriptionSerializer(subscription).data,
            }
        )

    @action(detail=False, methods=["get"], permission_classes=[IsOwnerOrManager])
    def discrepancies(self, request):
        """Отчёт о расхождениях остатка (TRU-61): последние 200 находок."""
        rows = (
            BalanceDiscrepancy.objects.for_tenant(request.user.organization)
            .select_related("subscription__child", "subscription__subscription_type_version")
            .order_by("-found_at")[:200]
        )
        return Response(
            [
                {
                    "id": str(row.id),
                    "found_at": row.found_at.isoformat(),
                    "subscription_id": str(row.subscription_id),
                    "child_id": str(row.subscription.child_id),
                    "child_name": row.subscription.child.full_name,
                    "subscription_name": row.subscription.subscription_type_version.name,
                    "cached_value": row.cached_value,
                    "recomputed_value": row.recomputed_value,
                }
                for row in rows
            ]
        )

    @action(detail=True, methods=["get"])
    def freezes(self, request, pk=None):
        subscription = self.get_object()
        return Response(SubscriptionFreezeSerializer(subscription.freezes.all(), many=True).data)

    def _fresh(self, subscription):
        # После заморозки у абонемента новый срок, статус и история заморозок.
        return SubscriptionSerializer(self.get_queryset().get(pk=subscription.pk)).data

    @action(detail=True, methods=["post"])
    def freeze(self, request, pk=None):
        subscription = self.get_object()
        data = FreezeRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        if subscription.status != Subscription.Status.ACTIVE:
            return Response(
                {"detail": "Заморозить можно только действующий абонемент."}, status=400
            )
        try:
            freeze_subscription(subscription, actor=request.user, **data.validated_data)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(self._fresh(subscription))

    @action(detail=True, methods=["post"])
    def unfreeze(self, request, pk=None):
        subscription = self.get_object()
        data = UnfreezeRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        if subscription.status != Subscription.Status.FROZEN:
            return Response({"detail": "Абонемент не заморожен."}, status=400)
        actual_end_date = data.validated_data.get("actual_end_date") or today_for_org(
            subscription.organization
        )
        try:
            unfreeze_subscription(subscription, actor=request.user, actual_end_date=actual_end_date)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(self._fresh(subscription))

    @staticmethod
    def _sale_terms(data):
        return {
            "starts_on": data["starts_on"],
            "discount_amount": data["discount_amount"],
            "discount_reason": data["discount_reason"],
            "paid_amount": data["paid_amount"],
            "payment_method": data["payment_method"],
        }

    @action(detail=True, methods=["post"])
    def renew(self, request, pk=None):
        """Продление (TRU-69): тот же ребёнок, направление и филиал, новый абонемент."""
        old = self.get_object()
        data = SaleRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        subscription_type = (
            get_selectable_subscription_types(old.organization, branch=old.branch)
            .filter(pk=data.validated_data["subscription_type_id"])
            .first()
        )
        if subscription_type is None:
            return Response(
                {"subscription_type_id": ["Этот абонемент не продаётся в филиале ребёнка."]},
                status=400,
            )
        try:
            new_sub, _payment = sell_renewal(
                old,
                actor=request.user,
                child=old.child,
                subscription_type_version=subscription_type.versions.latest(),
                direction=old.direction,
                branch=old.branch,
                **self._sale_terms(data.validated_data),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(SubscriptionSerializer(new_sub).data, status=201)

    @action(detail=False, methods=["post"])
    def sell(self, request):
        organization = request.user.organization
        data = SellRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        child = Child.objects.for_tenant(organization).filter(pk=values["child_id"]).first()
        branch = Branch.objects.for_tenant(organization).filter(pk=values["branch_id"]).first()
        direction = (
            Direction.objects.for_tenant(organization).filter(pk=values["direction_id"]).first()
        )
        subscription_type = (
            get_selectable_subscription_types(organization, branch=branch)
            .filter(pk=values["subscription_type_id"])
            .first()
        )
        errors = {}
        if child is None:
            errors["child_id"] = ["Ребёнок не найден."]
        if branch is None:
            errors["branch_id"] = ["Филиал не найден."]
        if direction is None:
            errors["direction_id"] = ["Направление не найдено."]
        if subscription_type is None:
            errors["subscription_type_id"] = ["Этот абонемент не продаётся в выбранном филиале."]
        if errors:
            return Response(errors, status=400)
        try:
            new_sub, _payment = sell_subscription(
                actor=request.user,
                child=child,
                subscription_type_version=subscription_type.versions.latest(),
                direction=direction,
                branch=branch,
                **self._sale_terms(values),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(SubscriptionSerializer(new_sub).data, status=201)

    @action(detail=False, methods=["get"])
    def types(self, request):
        """Типы абонементов, которые можно продать (?branch= — в этом филиале)."""
        organization = request.user.organization
        branch_id = request.query_params.get("branch")
        branch = (
            Branch.objects.for_tenant(organization).filter(pk=branch_id).first()
            if branch_id
            else None
        )
        return Response(
            [
                {
                    "id": str(item.id),
                    "name": item.name,
                    "price": str(item.price),
                    "is_unlimited": item.is_unlimited,
                    "quota_sessions": item.quota_sessions,
                    "duration_days": item.duration_days,
                }
                for item in get_selectable_subscription_types(organization, branch=branch)
            ]
        )

    @action(detail=False, methods=["get"])
    def next_lesson(self, request):
        from django.utils import timezone

        from domains.scheduling.schedule.models import Lesson

        child_id = request.query_params.get("child_id")
        direction_id = request.query_params.get("direction_id")
        lesson = (
            Lesson.objects.for_tenant(request.user.organization)
            .filter(
                group__direction_id=direction_id,
                group__memberships__child_id=child_id,
                group__memberships__left_at__isnull=True,
                starts_at__gte=timezone.now(),
            )
            .order_by("starts_at")
            .first()
        )
        return Response({"starts_at": lesson.starts_at.isoformat() if lesson else None})
