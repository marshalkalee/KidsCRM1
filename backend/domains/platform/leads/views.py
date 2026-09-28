import uuid
from datetime import timedelta

from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils import timezone
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
from .reporting import leads_workbook
from .serializers import (
    LeadBulkSerializer,
    LeadCommentSerializer,
    LeadRejectionReasonSerializer,
    LeadSerializer,
    LeadSourceSerializer,
    LeadStatusChangeSerializer,
    LeadStatusSerializer,
)
from .services import (
    LeadTransitionError,
    change_status,
    create_lead,
    find_phone_matches,
    visible_leads,
)


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


# Сортировка таблицы (TRU-95): ключ колонки → поле. «Дней в статусе» —
# это давность status_changed_at, поэтому направление обратное.
ORDERING = {
    "child_name": ["child_name", "parent_name"],
    "child_age": ["child_age"],
    "parent_name": ["parent_name"],
    "phone": ["phone"],
    "direction": ["direction__name"],
    "source": ["source__name"],
    "status": ["status"],
    "assigned_to": ["assigned_to__full_name"],
    "created_at": ["created_at"],
    "days_in_status": ["-status_changed_at"],
}
BULK_LIMIT = 200

BOARD_LIMIT = 20
CLOSED_DAYS = 30
CLOSED_STATUSES = [Lead.Status.PURCHASED, Lead.Status.REJECTED]


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

    Фильтры списка и доски (общие, чтобы доска и таблица показывали одно
    и то же — TRU-94/95):
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
            "branch", "direction", "source", "assigned_to", "rejection_reason", "converted_child"
        )
        if self.action not in ("list", "board", "export"):
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
        return self.ordered(qs)

    def ordered(self, qs):
        key = self.request.query_params.get("ordering", "")
        fields = ORDERING.get(key.lstrip("-"))
        if not fields:
            return qs.order_by("-created_at")
        if key.startswith("-"):
            fields = [field[1:] if field.startswith("-") else f"-{field}" for field in fields]
        # id — чтобы при равных значениях страницы не перемешивались.
        return qs.order_by(*fields, "-created_at", "id")

    @action(detail=False, methods=["post"])
    def bulk(self, request, version=None):
        """
        Массовые действия таблицы (TRU-95): {ids, action: "status"|"assign", …}.
        Статус меняется по одной заявке через change_status — у каждой своя
        запись в истории и своя проверка перехода; что не получилось, не
        отменяет остальное, а возвращается списком с причиной.
        """
        serializer = LeadBulkSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        leads = list(self.get_queryset().filter(pk__in=data["ids"]))
        updated, failed = 0, []
        for lead in leads:
            if data["action"] == "assign":
                lead.assigned_to = data.get("assigned_to")
                lead.save(update_fields=["assigned_to", "updated_at"])
                updated += 1
                continue
            try:
                change_status(
                    lead,
                    to_status=data["status"],
                    actor=request.user,
                    rejection_reason=data.get("rejection_reason"),
                    comment=data.get("comment", ""),
                )
                updated += 1
            except LeadTransitionError as exc:
                failed.append(
                    {
                        "id": str(lead.id),
                        "name": lead.child_name or lead.parent_name,
                        "error": str(exc),
                    }
                )
        return Response({"updated": updated, "failed": failed})

    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request, version=None):
        """Выгрузка отфильтрованных заявок в Excel — те же фильтры, что у таблицы."""
        response = HttpResponse(
            leads_workbook(self.get_queryset()),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = (
            f'attachment; filename="leads-{timezone.localdate():%Y-%m-%d}.xlsx"'
        )
        return response

    @action(detail=False, methods=["get"], url_path="check-phone")
    def check_phone(self, request, version=None):
        """Дубли по телефону для формы новой заявки (TRU-97)."""
        return Response(
            find_phone_matches(request.user.organization, request.query_params.get("phone", ""))
        )

    @action(detail=False, methods=["get"])
    def board(self, request, version=None):
        """
        Kanban-доска (TRU-94): колонки по статусам, в каждой — счётчик и
        первые `limit` карточек (свежие сверху). «Показать ещё» —
        `?column=<статус>&offset=N`, тогда в ответе одна колонка.

        Закрытые колонки («Купил», «Отказ») — только за последние
        CLOSED_DAYS дней, если период не задан явно: иначе через год доска
        тащила бы всю историю.
        """
        try:
            limit = min(max(int(request.query_params.get("limit", BOARD_LIMIT)), 1), 100)
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except ValueError:
            limit, offset = BOARD_LIMIT, 0
        qs = self.get_queryset()
        params = request.query_params
        if not params.get("created_from") and not params.get("created_to"):
            since = timezone.now() - timedelta(days=CLOSED_DAYS)
            qs = qs.exclude(status__in=CLOSED_STATUSES, status_changed_at__lt=since)
        statuses = Lead.Status.values
        if (column := params.get("column")) in statuses:
            statuses = [column]
        counts = dict(
            qs.order_by().values_list("status").annotate(n=Count("id")).values_list("status", "n")
        )
        context = self.get_serializer_context()
        columns = []
        for value in statuses:
            items = list(
                qs.filter(status=value).order_by("-status_changed_at", "-created_at")[
                    offset : offset + limit
                ]
            )
            columns.append(
                {
                    "status": value,
                    "label": Lead.Status(value).label,
                    "count": counts.get(value, 0),
                    "has_more": offset + len(items) < counts.get(value, 0),
                    "results": LeadSerializer(items, many=True, context=context).data,
                }
            )
        # Куда можно перетащить карточку из каждой колонки — доска подсвечивает
        # только допустимые (сервер всё равно проверит переход).
        transitions = {status: sorted(targets) for status, targets in Lead.TRANSITIONS.items()}
        return Response(
            {"columns": columns, "closed_days": CLOSED_DAYS, "transitions": transitions}
        )

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
