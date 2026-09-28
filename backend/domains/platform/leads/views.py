import uuid

from django.db.models import Count, Q
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from domains.platform.core.active_branch import get_active_branch
from domains.platform.core.audit import AuditLog
from domains.platform.core.permissions import IsStaffOfOrganization
from domains.platform.core.role_permissions import can_manage_lead_dictionaries, can_manage_leads
from domains.platform.core.viewsets import TenantModelViewSet

from .models import Lead, LeadComment, LeadRejectionReason, LeadSource
from .serializers import (
    LeadCommentSerializer,
    LeadRejectionReasonSerializer,
    LeadSerializer,
    LeadSourceSerializer,
    LeadStatusChangeSerializer,
    LeadStatusSerializer,
)
from .services import LeadTransitionError, change_status, create_lead, visible_leads


class CanManageLeads(IsStaffOfOrganization):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and can_manage_leads(request.user)


class CanManageLeadDictionaries(CanManageLeads):
    """Читать справочники — всем, кто работает с заявками; менять — владельцу
    и управляющему."""

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return request.method in ("GET", "HEAD", "OPTIONS") or can_manage_lead_dictionaries(
            request.user
        )


def _values(raw):
    return [value for value in (raw or "").split(",") if value]


def _uuids(values):
    """Кривой id в фильтре ничего не находит, а не роняет запрос."""
    result = []
    for value in values:
        try:
            result.append(uuid.UUID(value))
        except ValueError:
            continue
    return result


class LeadViewSet(TenantModelViewSet):
    """
    Заявки воронки продаж (TRU-99).

    Фильтры списка (общие для будущих доски и таблицы — TRU-94/95):
    status, source, direction, branch, assigned_to — через запятую
    (assigned_to=me — мои); q — имя родителя, ребёнка или телефон;
    created_from / created_to — дата создания, ГГГГ-ММ-ДД. Активный
    филиал из X-Branch-Id сужает список, как и в остальных экранах.
    """

    serializer_class = LeadSerializer
    permission_classes = [IsAuthenticated, CanManageLeads]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = visible_leads(self.request.user).select_related(
            "branch", "direction", "source", "assigned_to", "rejection_reason"
        )
        if self.action != "list":
            return qs
        params = self.request.query_params
        branch = get_active_branch(self.request)
        if branch is not None:
            qs = qs.filter(branch=branch)
        if statuses := _values(params.get("status")):
            qs = qs.filter(status__in=statuses)
        for field in ("source", "direction", "branch", "assigned_to"):
            values = _values(params.get(field))
            if field == "assigned_to":
                values = [str(self.request.user.pk) if value == "me" else value for value in values]
            if values:
                qs = qs.filter(**{f"{field}_id__in": _uuids(values)})
        if created_from := parse_date(params.get("created_from") or ""):
            qs = qs.filter(created_at__date__gte=created_from)
        if created_to := parse_date(params.get("created_to") or ""):
            qs = qs.filter(created_at__date__lte=created_to)
        if q := (params.get("q") or "").strip():
            digits = "".join(ch for ch in q if ch.isdigit())
            condition = Q(parent_name__icontains=q) | Q(child_name__icontains=q)
            if len(digits) >= 3:
                condition |= Q(phone__contains=digits)
            qs = qs.filter(condition)
        return qs

    def perform_create(self, serializer):
        data = dict(serializer.validated_data)
        # Ответственный по умолчанию — тот, кто завёл заявку (TRU-97).
        data.setdefault("assigned_to", self.request.user)
        serializer.instance = create_lead(
            organization=self.request.user.organization, actor=self.request.user, **data
        )

    def perform_destroy(self, instance):
        AuditLog.record(self.request.user, AuditLog.Action.DELETE, instance)
        instance.delete()

    @action(detail=True, methods=["post"], url_path="status")
    def set_status(self, request, pk=None, version=None):
        lead = self.get_object()
        serializer = LeadStatusSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        try:
            lead = change_status(
                lead,
                to_status=serializer.validated_data["status"],
                actor=request.user,
                rejection_reason=serializer.validated_data.get("rejection_reason"),
                comment=serializer.validated_data.get("comment", ""),
            )
        except LeadTransitionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(LeadSerializer(lead, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None, version=None):
        lead = self.get_object()
        changes = lead.status_changes.select_related("changed_by", "rejection_reason")
        return Response(LeadStatusChangeSerializer(changes, many=True).data)

    @action(detail=True, methods=["get", "post"])
    def comments(self, request, pk=None, version=None):
        lead = self.get_object()
        if request.method == "POST":
            serializer = LeadCommentSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save(organization=lead.organization, lead=lead, author=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        comments = (
            LeadComment.objects.for_tenant(lead.organization)
            .filter(lead=lead)
            .select_related("author")
        )
        return Response(LeadCommentSerializer(comments, many=True).data)


class LeadDictionaryViewSet(TenantModelViewSet):
    """
    Справочник воронки (TRU-93). Удаления нет — только архивация
    (PATCH is_active=false): в старых заявках значение должно остаться.
    Порядок: активные, затем самые частые, затем по алфавиту.
    ?active=1 — только активные (для выбора в новой заявке).
    """

    permission_classes = [IsAuthenticated, CanManageLeadDictionaries]
    http_method_names = ["get", "post", "patch", "head", "options"]
    pagination_class = None
    model = None
    usage = None

    def get_queryset(self):
        qs = self.model.objects.for_tenant(self.request.user.organization).annotate(
            usage_count=self.usage
        )
        if self.request.query_params.get("active") in ("1", "true"):
            qs = qs.filter(is_active=True)
        return qs.order_by("-is_active", "-usage_count", "name")


class LeadSourceViewSet(LeadDictionaryViewSet):
    serializer_class = LeadSourceSerializer
    model = LeadSource
    usage = Count("leads", filter=Q(leads__deleted_at__isnull=True))


class LeadRejectionReasonViewSet(LeadDictionaryViewSet):
    serializer_class = LeadRejectionReasonSerializer
    model = LeadRejectionReason
    # По событиям отказа, а не по текущим заявкам: вернули заявку в работу —
    # отказ всё равно был и в отчёт по причинам попадает.
    usage = Count("status_changes", filter=Q(status_changes__to_status=Lead.Status.REJECTED))
