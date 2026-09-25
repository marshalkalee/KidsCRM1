import uuid
from decimal import Decimal

from django.db.models import Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from domains.money.subscriptions.debt import debt_by_child
from domains.money.subscriptions.models import Subscription
from domains.platform.core.active_branch import get_active_branch
from domains.platform.core.permissions import IsOwnerOrManagerOrAdmin, IsStaffOfOrganization
from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number
from domains.platform.core.role_permissions import (
    can_manage_children,
    can_view_client_money,
    can_view_phone,
)
from domains.scheduling.groups.models import GroupMembership

from . import search
from .child_list import active_group_branch_names, branch_names, list_children
from .models import Child, ChildContact, CommunicationLog, ParentContact
from .parents import DELETE_BLOCKED_MESSAGE, can_delete_parent, parent_money
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

    @action(detail=True, methods=["get"])
    def card(self, request, pk=None):
        """Шапка карточки ребёнка во frontend2 (TRU-82): сам ребёнок,
        филиалы/направления/текущие группы и — для ролей с
        can_view_client_money — последний абонемент и долг. Одним запросом,
        чтобы шапка не собиралась из пяти."""
        child = self.get_object()
        organization = request.user.organization
        directions = list(child.directions.all().prefetch_related("branches"))
        memberships = list(
            GroupMembership.objects.for_tenant(organization)
            .filter(child=child, left_at__isnull=True)
            .select_related("group__branch")
        )
        # Как child_list.branch_names: филиалы групп, без групп — направлений.
        branches = {m.group.branch_id: m.group.branch.name for m in memberships} or {
            branch.id: branch.name
            for direction in directions
            for branch in direction.branches.all()
        }
        money = None
        if can_view_client_money(request.user):
            subscription = (
                Subscription.objects.for_tenant(organization)
                .filter(child=child)
                .select_related("subscription_type_version")
                .order_by("-starts_on")
                .first()
            )
            debt = debt_by_child(organization, [child.id]).get(child.id, Decimal(0))
            money = {
                "debt": str(debt),
                "subscription": subscription
                and {
                    "id": str(subscription.id),
                    "name": subscription.subscription_type_version.name,
                    "starts_on": subscription.starts_on,
                    "ends_on": subscription.ends_on,
                    "status": subscription.status,
                    "sessions_remaining": subscription.sessions_remaining_cache,
                },
            }
        return Response(
            {
                "child": self.get_serializer(child).data,
                "directions": [{"id": str(d.id), "name": d.name} for d in directions],
                "branches": [
                    {"id": str(branch_id), "name": name}
                    for branch_id, name in sorted(branches.items(), key=lambda item: item[1])
                ],
                "groups": [
                    {"id": str(m.group_id), "name": m.group.name, "joined_at": m.joined_at}
                    for m in memberships
                ],
                "money": money,
                "permissions": {
                    "can_edit": can_manage_children(request.user),
                    "can_manage_contacts": can_manage_children(request.user),
                    "can_log_communications": can_manage_children(request.user),
                },
            }
        )


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
            "phones", "child_links__child"
        )
        # ?q= — поиск в списке родителей frontend2: по имени или по цифрам
        # телефона (как глобальный поиск, от 3 символов цифр).
        query = (self.request.query_params.get("q") or "").strip()
        if query:
            digits = "".join(ch for ch in query if ch.isdigit())
            condition = Q(full_name__icontains=query)
            if len(digits) >= 3:
                condition |= Q(phones__number__contains=digits) | Q(whatsapp__contains=digits)
            qs = qs.filter(condition).distinct()
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

    def destroy(self, request, *args, **kwargs):
        parent = self.get_object()
        if not can_delete_parent(request.user.organization, parent):
            return Response({"detail": DELETE_BLOCKED_MESSAGE}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["get"])
    def card(self, request, pk=None):
        """Карточка родителя во frontend2 (TRU-83): родитель, его дети
        (из всех филиалов) с ролями и — для can_view_client_money —
        суммарный долг и последние оплаты по всем детям."""
        parent = self.get_object()
        organization = request.user.organization
        links = (
            ChildContact.objects.for_tenant(organization)
            .filter(parent_contact=parent, child__deleted_at__isnull=True)
            .select_related("child")
            .prefetch_related(
                "child__directions__branches", "child__group_memberships__group__branch"
            )
        )
        money = None
        if can_view_client_money(request.user):
            summary = parent_money(organization, parent)
            money = {
                "total_debt": str(summary["total_debt"]),
                "payments": [
                    {
                        "id": str(payment.id),
                        "paid_at": payment.paid_at,
                        "amount": str(payment.amount),
                        "method": payment.method,
                        "method_label": payment.get_method_display(),
                        "status": payment.status,
                        "child_id": str(payment.subscription.child_id),
                        "child_name": payment.subscription.child.full_name,
                        "subscription_name": payment.subscription.subscription_type_version.name,
                    }
                    for payment in summary["payments"]
                ],
            }
        return Response(
            {
                "parent": self.get_serializer(parent).data,
                "children": [
                    {
                        "id": str(link.child_id),
                        "link_id": str(link.id),
                        "full_name": link.child.full_name,
                        "age": link.child.age,
                        "status": link.child.status,
                        "role": link.role,
                        "is_payer": link.is_payer,
                        "is_primary_contact": link.is_primary_contact,
                        "branch_names": branch_names(
                            link.child, active_group_branch_names(link.child)
                        ),
                    }
                    for link in links
                ],
                "money": money,
                "permissions": {
                    "can_edit": can_manage_children(request.user),
                    "can_delete": can_manage_children(request.user),
                    "can_log_communications": can_manage_children(request.user),
                },
            }
        )


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
        qs = (
            ChildContact.objects.for_tenant(self.request.user.organization)
            .select_related("child", "parent_contact")
            .prefetch_related("parent_contact__phones")
        )
        child_id = self.request.query_params.get("child")
        if child_id:
            qs = qs.filter(child_id=child_id)
        parent_contact_id = self.request.query_params.get("parent_contact")
        if parent_contact_id:
            qs = qs.filter(parent_contact_id=parent_contact_id)
        return qs


class CommunicationLogViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """
    Вкладка «Коммуникации» (ТЗ п. 4.1): ?child=<id> — история ребёнка,
    ?parent_contact=<id> — сводная история родителя. Append-only: нет
    update/delete. Читают все сотрудники, пишут владелец/управляющий/
    администратор (как COMMUNICATION_LOG_MANAGE_ROLES в вебе).
    """

    serializer_class = CommunicationLogSerializer

    def get_permissions(self):
        if self.action == "create":
            return [IsOwnerOrManagerOrAdmin()]
        return [IsStaffOfOrganization()]

    def get_queryset(self):
        qs = CommunicationLog.objects.for_tenant(self.request.user.organization).select_related(
            "author", "child", "parent_contact"
        )
        child_id = self.request.query_params.get("child")
        if child_id:
            qs = qs.filter(child_id=child_id)
        parent_contact_id = self.request.query_params.get("parent_contact")
        if parent_contact_id:
            qs = qs.filter(parent_contact_id=parent_contact_id)
        # ?family=<parent_id> — сводная лента карточки родителя: всё по
        # любому из его детей, не только записи с явно отмеченным им
        # контактом (как parent_card в вебе).
        family_id = self.request.query_params.get("family")
        if family_id:
            try:
                family_id = uuid.UUID(family_id)
            except ValueError:
                return qs.none()
            qs = qs.filter(
                child__contacts__parent_contact_id=family_id,
                child__contacts__deleted_at__isnull=True,
            ).distinct()
        return qs

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)


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
