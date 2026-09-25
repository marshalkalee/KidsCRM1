from django.db.models import Count, Q
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.response import Response

from domains.platform.core.permissions import (
    BranchScopedPermission,
    IsNotAccountant,
    IsOwner,
    IsOwnerOrManager,
    IsStaffOfOrganization,
)

from .forms import TIMEZONE_CHOICES, OrganizationSettingsForm
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


def _settings_payload(form):
    return {
        **{name: form.initial.get(name) for name in form.fields},
        "timezones": [value for value, _label in TIMEZONE_CHOICES],
    }


@api_view(["GET", "PUT"])
@permission_classes([IsOwner])
def organization_settings(request):
    """Экран «Организация» во frontend2 (TRU-85): название, часовой пояс,
    пороги автостатусов (с фолбэком на значения по умолчанию). Запись —
    через ту же OrganizationSettingsForm, что у веба и мастера онбординга:
    остальные ключи settings (например "onboarding") не затираются."""
    organization = request.user.organization
    if request.method == "PUT":
        form = OrganizationSettingsForm(request.data)
        if not form.is_valid():
            return Response(
                {field: list(messages) for field, messages in form.errors.items()},
                status=status.HTTP_400_BAD_REQUEST,
            )
        form.save(organization)
    return Response(_settings_payload(OrganizationSettingsForm.for_organization(organization)))


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
        # После фильтра по staff: иначе его join размножил бы строки и счётчик.
        return qs.annotate(rooms_count=Count("rooms", filter=Q(rooms__deleted_at__isnull=True)))

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
        qs = Room.objects.for_tenant(self.request.user.organization).select_related("branch")
        branch_id = self.request.query_params.get("branch")
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        return qs


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
