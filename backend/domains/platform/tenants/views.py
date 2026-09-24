from rest_framework import viewsets
from rest_framework.generics import RetrieveUpdateAPIView

from domains.platform.core.permissions import (
    BranchScopedPermission,
    IsNotAccountant,
    IsOwner,
    IsOwnerOrManager,
    IsStaffOfOrganization,
)

from .models import Branch, Direction, Room
from .serializers import (
    BranchSerializer,
    DirectionSerializer,
    OrganizationSerializer,
    RoomSerializer,
)


class OrganizationMeView(RetrieveUpdateAPIView):
    """
    Только текущая организация — только владелец видит и редактирует.
    Администратор не видит сводку организации (ТЗ п. 2).
    """

    serializer_class = OrganizationSerializer
    permission_classes = [IsOwner]

    def get_object(self):
        return self.request.user.organization


class BranchViewSet(viewsets.ModelViewSet):
    """
    Список и детали — все сотрудники.
    Создание/изменение/удаление — только владелец или управляющий.
    """

    serializer_class = BranchSerializer
    permission_classes = [IsStaffOfOrganization]

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsOwnerOrManager()]
        return [BranchScopedPermission()]

    def get_queryset(self):
        user = self.request.user
        qs = Branch.objects.for_tenant(user.organization)
        # Управляющий видит только свои филиалы
        if user.role == user.Role.MANAGER:
            qs = qs.filter(staff=user)
        return qs

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)


class RoomViewSet(viewsets.ModelViewSet):
    """
    Просмотр — все сотрудники.
    Создание/изменение/удаление — не бухгалтер.
    """

    serializer_class = RoomSerializer
    permission_classes = [IsStaffOfOrganization]

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsNotAccountant()]
        return [IsStaffOfOrganization()]

    def get_queryset(self):
        return Room.objects.for_tenant(self.request.user.organization).select_related("branch")


class DirectionViewSet(viewsets.ModelViewSet):
    serializer_class = DirectionSerializer
    permission_classes = [IsStaffOfOrganization]

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsOwnerOrManager()]
        return [IsStaffOfOrganization()]

    def get_queryset(self):
        return Direction.objects.for_tenant(self.request.user.organization)

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)
