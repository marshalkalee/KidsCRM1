from django.db.models import Count
from django.utils import timezone
from rest_framework import filters, status
from rest_framework.decorators import action
from rest_framework.response import Response

from domains.platform.core.permissions import (
    IsOwnerOrManager,
    IsStaffOfOrganization,
)
from domains.platform.core.viewsets import TenantModelViewSet

from . import queries
from .models import Group, GroupMembership
from .serializers import GroupMembershipSerializer, GroupSerializer


class GroupViewSet(TenantModelViewSet):
    serializer_class = GroupSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "direction__name", "branch__name"]
    ordering_fields = ["name", "capacity", "status", "created_at"]
    ordering = ["name"]

    def get_permissions(self):
        if self.action in ["create", "update", "partial_update", "destroy"]:
            return [IsOwnerOrManager()]
        return [IsStaffOfOrganization()]

    def get_queryset(self):
        qs = queries.with_members_count(
            Group.objects.for_tenant(self.request.user.organization)
            .select_related("branch", "direction")
            .prefetch_related("teachers", "schedule_templates__slots__room")
            .annotate(teachers_count=Count("teachers", distinct=True))
        )
        user = self.request.user
        if user.role == "teacher":
            qs = qs.filter(teachers=user)

        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        branch_id = self.request.query_params.get("branch")
        if branch_id:
            qs = qs.filter(branch_id=branch_id)

        direction_id = self.request.query_params.get("direction")
        if direction_id:
            qs = qs.filter(direction_id=direction_id)

        teacher_id = self.request.query_params.get("teacher")
        if teacher_id:
            qs = qs.filter(teachers__id=teacher_id)

        if self.request.query_params.get("for_enrollment"):
            qs = qs.filter(status=Group.Status.ACTIVE)

        return qs

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)

    def perform_destroy(self, instance):
        instance.status = Group.Status.CLOSED
        instance.save(update_fields=["status", "updated_at"])

    @action(detail=True, methods=["get"])
    def members(self, request, pk=None):
        group = self.get_object()
        memberships = (
            GroupMembership.objects.for_tenant(request.user.organization)
            .filter(group=group, left_at__isnull=True)
            .select_related("child")
            .order_by("child__full_name")
        )
        serializer = GroupMembershipSerializer(memberships, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def add_member(self, request, pk=None):
        group = self.get_object()
        serializer = GroupMembershipSerializer(
            data={**request.data, "group": group.id},
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def remove_member(self, request, pk=None):
        group = self.get_object()
        child_id = request.data.get("child_id")
        left_at = request.data.get("left_at")

        membership = (
            GroupMembership.objects.for_tenant(request.user.organization)
            .filter(
                group=group,
                child_id=child_id,
                left_at__isnull=True,
            )
            .first()
        )

        if not membership:
            return Response(
                {"detail": "Ребёнок не найден в этой группе."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Без даты — «вышел сегодня» (раньше left_at=None молча ничего не менял).
        membership.left_at = left_at or timezone.localdate()
        membership.save(update_fields=["left_at", "updated_at"])
        return Response(GroupMembershipSerializer(membership).data)

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        group = self.get_object()
        memberships = (
            GroupMembership.objects.for_tenant(request.user.organization)
            .filter(group=group)
            .select_related("child")
            .order_by("-joined_at")
        )
        serializer = GroupMembershipSerializer(memberships, many=True)
        return Response(serializer.data)
