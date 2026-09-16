from django.db.models import Q
from rest_framework import viewsets

from domains.platform.core.permissions import IsOwnerOrManagerOrAdmin, IsStaffOfOrganization
from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number

from .models import Child, ParentContact
from .serializers import ChildSerializer, ParentContactSerializer


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


class ParentContactViewSet(viewsets.ModelViewSet):
    """
    Просмотр — все сотрудники (телефоны скрыты для ролей без
    can_view_phone — см. ParentContactSerializer.to_representation).
    Создание/изменение/удаление — владелец, управляющий или администратор.
    """

    serializer_class = ParentContactSerializer
    permission_classes = [IsStaffOfOrganization]

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsOwnerOrManagerOrAdmin()]
        return [IsStaffOfOrganization()]

    def get_queryset(self):
        qs = ParentContact.objects.for_tenant(self.request.user.organization).prefetch_related(
            "phones"
        )
        # ?phone= — поиск по любому из телефонов родителя или по WhatsApp
        # (ТЗ п. 4.1: телефон — фактический идентификатор клиента).
        phone_query = self.request.query_params.get("phone")
        if phone_query:
            try:
                normalized = normalize_phone_number(phone_query)
            except InvalidPhoneNumberError:
                return qs.none()
            qs = qs.filter(Q(phones__number=normalized) | Q(whatsapp=normalized)).distinct()
        return qs

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)
