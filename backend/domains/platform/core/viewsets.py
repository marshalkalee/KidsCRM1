from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from .permissions import IsStaffOfOrganization


class TenantModelViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsStaffOfOrganization]

    def get_queryset(self):
        raise NotImplementedError(f"{self.__class__.__name__} должен реализовать get_queryset()")

    def perform_create(self, serializer):
        serializer.save(organization=self.request.organization)
