from django.db.models import Q
from rest_framework import viewsets

from domains.platform.core.permissions import IsOwnerOrManagerOrAdmin, IsStaffOfOrganization
from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number

from .models import Child, ChildContact, CommunicationLog, ParentContact
from .serializers import (
    ChildContactSerializer,
    ChildSerializer,
    CommunicationLogSerializer,
    ParentContactSerializer,
)


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


class ChildContactViewSet(viewsets.ModelViewSet):
    """
    Связь ребёнок <-> родитель/контактное лицо (ТЗ п. 1.2.1). Просмотр —
    все сотрудники; привязать/отвязать/сменить роль или плательщика —
    владелец, управляющий или администратор. organization на связи
    выводится из child (ChildContact.save()) — здесь не задаётся.
    """

    serializer_class = ChildContactSerializer
    permission_classes = [IsStaffOfOrganization]

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsOwnerOrManagerOrAdmin()]
        return [IsStaffOfOrganization()]

    def get_queryset(self):
        qs = ChildContact.objects.for_tenant(self.request.user.organization).select_related(
            "child", "parent_contact"
        )
        child_id = self.request.query_params.get("child")
        if child_id:
            qs = qs.filter(child_id=child_id)
        parent_contact_id = self.request.query_params.get("parent_contact")
        if parent_contact_id:
            qs = qs.filter(parent_contact_id=parent_contact_id)
        return qs


class CommunicationLogViewSet(viewsets.ModelViewSet):
    """
    /api/v1/communications/ (ТЗ п. 3.1, п. 4.1) — вкладка «Коммуникации»
    карточки ребёнка и запись факта обзвона о переносе занятия (TRU-49,
    LessonViewSet.mark_called). Append-only (см. CommunicationLog.__doc__)
    — только просмотр и создание, без изменения/удаления.
    """

    serializer_class = CommunicationLogSerializer
    permission_classes = [IsStaffOfOrganization]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = CommunicationLog.objects.for_tenant(self.request.user.organization).select_related(
            "parent_contact", "author"
        )
        child_id = self.request.query_params.get("child")
        if child_id:
            qs = qs.filter(child_id=child_id)
        date_from = self.request.query_params.get("date_from")
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        date_to = self.request.query_params.get("date_to")
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        return qs

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)
