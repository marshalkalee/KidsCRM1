from rest_framework import viewsets
from rest_framework.generics import RetrieveUpdateAPIView

from domains.platform.core.permissions import IsStaffOfOrganization

from .models import Branch, Room
from .serializers import BranchSerializer, OrganizationSerializer, RoomSerializer


class OrganizationMeView(RetrieveUpdateAPIView):
    """
    Только текущая организация пользователя, не список организаций —
    список позволил бы одному тенанту перечислить остальных (см. ADR-001).
    """

    serializer_class = OrganizationSerializer
    permission_classes = [IsStaffOfOrganization]

    def get_object(self):
        return self.request.user.organization


class BranchViewSet(viewsets.ModelViewSet):
    serializer_class = BranchSerializer
    permission_classes = [IsStaffOfOrganization]

    def get_queryset(self):
        return Branch.objects.for_tenant(self.request.user.organization)

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)


class RoomViewSet(viewsets.ModelViewSet):
    serializer_class = RoomSerializer
    permission_classes = [IsStaffOfOrganization]

    def get_queryset(self):
        return Room.objects.for_tenant(self.request.user.organization).select_related("branch")
