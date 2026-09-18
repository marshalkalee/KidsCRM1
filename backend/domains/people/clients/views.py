from rest_framework import viewsets

from domains.platform.core.permissions import IsOwnerOrManagerOrAdmin, IsStaffOfOrganization

from .models import Child
from .serializers import ChildSerializer


class ChildViewSet(viewsets.ModelViewSet):
    """
    Просмотр — все сотрудники организации (в т.ч. преподаватель, но без
    административных полей — см. ChildSerializer.to_representation).
    Создание/изменение/удаление — владелец, управляющий или администратор;
    не преподаватель и не бухгалтер.
    """

    serializer_class = ChildSerializer
    permission_classes = [IsStaffOfOrganization]

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsOwnerOrManagerOrAdmin()]
        return [IsStaffOfOrganization()]

    def get_queryset(self):
        return Child.objects.for_tenant(self.request.user.organization).prefetch_related(
            "directions"
        )

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)
