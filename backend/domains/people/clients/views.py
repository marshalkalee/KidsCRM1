from django.db.models import Q
from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from domains.platform.core.active_branch import get_active_branch
from domains.platform.core.permissions import IsOwnerOrManagerOrAdmin, IsStaffOfOrganization
from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number
from domains.platform.core.role_permissions import can_view_client_money, can_view_phone

from . import search
from .child_list import list_children
from .models import Child, ChildContact, ParentContact
from .serializers import ChildContactSerializer, ChildSerializer, ParentContactSerializer


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


@api_view(["GET"])
@permission_classes([IsStaffOfOrganization])
def global_search_api(request):
    """Поиск в шапке frontend2 (TRU-80): тот же сервис, что у старого веба
    (search.global_search). Ссылки строит фронт по type + id."""
    results = search.global_search(
        request.user.organization,
        request.query_params.get("q"),
        can_view_phone=can_view_phone(request.user),
    )
    return Response({"results": results})


@api_view(["GET"])
@permission_classes([IsStaffOfOrganization])
def child_table_api(request):
    """Таблица детей frontend2 (TRU-81): фильтры, сортировка и пагинация на
    сервере — тот же сервис, что у старой веб-страницы (child_list).
    Без ?branch= берётся активный филиал из шапки (X-Branch-Id)."""
    params = request.query_params.dict()
    if not params.get("branch"):
        active_branch = get_active_branch(request)
        if active_branch:
            params["branch"] = str(active_branch.pk)
    show_money = can_view_client_money(request.user)
    rows, total = list_children(request.user.organization, params, show_money=show_money)
    return Response({"results": rows, "count": total, "show_money": show_money})
