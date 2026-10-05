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

from domains.people.clients.models import Child
from domains.platform.core.active_branch import get_active_branch
from domains.platform.core.audit import AuditLog
from domains.platform.core.permissions import IsStaffOfOrganization
from domains.platform.core.role_permissions import can_manage_lead_dictionaries, can_manage_leads
from domains.platform.core.utils import day_bounds_for_org
from domains.platform.core.viewsets import TenantModelViewSet

from .conversion import LeadConversionError, conversion_preview, convert_lead
from .models import (
    Lead,
    LeadComment,
    LeadKind,
    LeadRejectionReason,
    LeadSource,
    LeadStage,
    LeadStatusChange,
)
from .reporting import leads_workbook
from .sale import LeadSaleError, sale_options, sell_from_lead
from .serializers import (
    LeadBulkSerializer,
    LeadCommentSerializer,
    LeadConversionQuerySerializer,
    LeadConversionSerializer,
    LeadRejectionReasonSerializer,
    LeadSaleSerializer,
    LeadSerializer,
    LeadSourceSerializer,
    LeadStageSerializer,
    LeadStatusChangeSerializer,
    LeadStatusSerializer,
    TrialBookingCancelSerializer,
    TrialBookingSerializer,
    TrialLessonSerializer,
)
from .services import (
    LeadTransitionError,
    RenewalError,
    change_status,
    create_lead,
    create_renewal_lead,
    find_phone_matches,
    leave_hidden_stage,
    move_to_stage,
    visible_leads,
)
from .stages import Funnel, org_stages
from .trial_booking import (
    TrialBookingError,
    book_trial,
    cancel_trial_booking,
    reschedule_trial_booking,
    trial_lesson_candidates,
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


def _kind(params):
    return LeadKind.RENEWAL if params.get("kind") == LeadKind.RENEWAL else LeadKind.NEW


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


def _filter_stages(qs, funnel, stage_ids):
    """Заявки на этапах: свой — по ссылке, системный — роль без своего этапа."""
    condition = Q(pk__in=[])
    for stage_id in stage_ids:
        stage = funnel.by_id.get(stage_id)
        if stage is None:
            continue
        if stage.is_system:
            condition |= Q(status=stage.role, stage__isnull=True)
        else:
            condition |= Q(stage=stage)
    return qs.filter(condition)


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
            "branch",
            "direction",
            "source",
            "assigned_to",
            "rejection_reason",
            "converted_child",
            "sold_subscription__subscription_type_version",
        )
        if self.action not in ("list", "board", "export"):
            return qs
        params = self.request.query_params
        # Новые и продления — разные воронки (TRU-98), по умолчанию — новые.
        qs = qs.filter(kind=_kind(params))
        branch = get_active_branch(self.request)
        if branch is not None:
            qs = qs.filter(branch=branch)
        if statuses := _values(params.get("status")):
            qs = qs.filter(status__in=statuses)
        if stages := _uuids(_values(params.get("stage"))):
            qs = _filter_stages(qs, Funnel(self.request.user.organization), stages)
        for field in ("source", "direction", "branch", "assigned_to"):
            values = _values(params.get(field))
            if field == "assigned_to":
                values = [str(self.request.user.pk) if value == "me" else value for value in values]
            if values:
                qs = qs.filter(**{f"{field}_id__in": _uuids(values)})
        # Дни — по времени центра, а не UTC: заявка в 02:00 по Алматы — это
        # уже сегодня. Так же считает воронка в аналитике (TRU-115), и список
        # по клику «сейчас на этапе» совпадает с её цифрой.
        organization = self.request.user.organization
        if created_from := parse_date(params.get("created_from") or ""):
            qs = qs.filter(created_at__gte=day_bounds_for_org(organization, created_from)[0])
        if created_to := parse_date(params.get("created_to") or ""):
            qs = qs.filter(created_at__lte=day_bounds_for_org(organization, created_to)[1])
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
            leads_workbook(self.get_queryset(), Funnel(request.user.organization)),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = (
            f'attachment; filename="leads-{timezone.localdate():%Y-%m-%d}.xlsx"'
        )
        return response

    @action(detail=False, methods=["post"])
    def renewal(self, request, version=None):
        """
        Продление по клиенту (TRU-98): {child, comment?} — для кнопки на экране
        «Продления» (TRU-69). Уже есть открытое продление — вернёт его (200),
        иначе создаст (201).
        """
        child = (
            Child.objects.for_tenant(request.user.organization)
            .filter(pk__in=_uuids([str(request.data.get("child", ""))]))
            .first()
        )
        if child is None:
            return Response({"child": ["Ребёнок не найден."]}, status=status.HTTP_400_BAD_REQUEST)
        try:
            lead, created = create_renewal_lead(
                child, actor=request.user, comment=request.data.get("comment", "")
            )
        except RenewalError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            LeadSerializer(lead, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

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
        kind = _kind(params)
        funnel = Funnel(request.user.organization)
        stages = funnel.visible(kind)
        # ?column — id этапа; по-старому роль — её системный этап.
        if column := params.get("column"):
            stages = [s for s in stages if column in (str(s.pk), s.role if s.is_system else None)]
        counts = {
            (role, stage_id): n
            for role, stage_id, n in qs.order_by()
            .values_list("status", "stage")
            .annotate(n=Count("id"))
            .values_list("status", "stage", "n")
        }
        context = {**self.get_serializer_context(), "funnel": funnel}
        columns = []
        for stage in stages:
            if stage.is_system:
                # Заявки скрытых этапов уже переведены на системный
                # (leave_hidden_stage), поэтому здесь — роль без своего этапа.
                count = counts.get((stage.role, None), 0)
                items_qs = qs.filter(status=stage.role, stage__isnull=True)
            else:
                count = counts.get((stage.role, stage.pk), 0)
                items_qs = qs.filter(stage=stage)
            items = list(
                items_qs.order_by("-status_changed_at", "-created_at")[offset : offset + limit]
            )
            columns.append(
                {
                    "stage": str(stage.pk),
                    "status": stage.role,
                    "label": stage.name,
                    "color": stage.color,
                    "is_system": stage.is_system,
                    "count": count,
                    "has_more": offset + len(items) < count,
                    "results": LeadSerializer(items, many=True, context=context).data,
                }
            )
        # Куда можно перетащить карточку — доска подсвечивает только
        # допустимые (сервер всё равно проверит переход). transitions — по
        # ролям, как до TRU-154; stage_transitions — по этапам центра.
        transitions = {
            status: sorted(targets) for status, targets in Lead.transitions_for(kind).items()
        }
        return Response(
            {
                "columns": columns,
                "closed_days": CLOSED_DAYS,
                "transitions": transitions,
                "stage_transitions": funnel.transitions(kind),
            }
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
        data = serializer.validated_data
        try:
            if stage := data.get("stage"):
                lead = move_to_stage(
                    lead,
                    stage=stage,
                    actor=request.user,
                    rejection_reason=data.get("rejection_reason"),
                    comment=data.get("comment", ""),
                )
            else:
                lead = change_status(
                    lead,
                    to_status=data["status"],
                    actor=request.user,
                    rejection_reason=data.get("rejection_reason"),
                    comment=data.get("comment", ""),
                )
        except LeadTransitionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(LeadSerializer(lead, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["get"], url_path="trial-lessons")
    def trial_lessons(self, request, pk=None, version=None):
        lead = self.get_object()
        try:
            lessons = trial_lesson_candidates(
                lead, for_reschedule=request.query_params.get("mode") == "reschedule"
            )
        except TrialBookingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            TrialLessonSerializer(lessons, many=True, context=self.get_serializer_context()).data
        )

    @action(detail=True, methods=["post"], url_path="book-trial")
    def book_trial_action(self, request, pk=None, version=None):
        lead = self.get_object()
        serializer = TrialBookingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            lead, _enrollment = book_trial(
                lead, serializer.validated_data["lesson"], actor=request.user
            )
        except TrialBookingError as exc:
            response_status = (
                status.HTTP_409_CONFLICT if exc.code == "capacity" else status.HTTP_400_BAD_REQUEST
            )
            return Response({"detail": str(exc)}, status=response_status)
        return Response(
            LeadSerializer(lead, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="cancel-trial")
    def cancel_trial_action(self, request, pk=None, version=None):
        lead = self.get_object()
        serializer = TrialBookingCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            lead, _enrollment = cancel_trial_booking(
                lead, reason=serializer.validated_data["reason"], actor=request.user
            )
        except TrialBookingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(LeadSerializer(lead, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"], url_path="reschedule-trial")
    def reschedule_trial_action(self, request, pk=None, version=None):
        lead = self.get_object()
        serializer = TrialBookingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            lead, _enrollment = reschedule_trial_booking(
                lead, serializer.validated_data["lesson"], actor=request.user
            )
        except TrialBookingError as exc:
            response_status = (
                status.HTTP_409_CONFLICT if exc.code == "capacity" else status.HTTP_400_BAD_REQUEST
            )
            return Response({"detail": str(exc)}, status=response_status)
        return Response(LeadSerializer(lead, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["get", "post"], url_path="conversion")
    def conversion(self, request, pk=None, version=None):
        """Предпросмотр дублей и явное подтверждение конвертации TRU-102."""
        lead = self.get_object()
        if request.method == "GET":
            query = LeadConversionQuerySerializer(data=request.query_params)
            query.is_valid(raise_exception=True)
            return Response(conversion_preview(lead, **query.validated_data))

        serializer = LeadConversionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            lead, created = convert_lead(lead, actor=request.user, data=serializer.validated_data)
        except (LeadConversionError, Child.DoesNotExist) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            LeadSerializer(lead, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get", "post"], url_path="sale")
    def sale(self, request, pk=None, version=None):
        """Подбор абонемента/группы и атомарное закрытие продажи TRU-103."""
        lead = self.get_object()
        if request.method == "GET":
            return Response(sale_options(lead))

        serializer = LeadSaleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            lead, membership, created = sell_from_lead(
                lead, actor=request.user, data=serializer.validated_data
            )
        except LeadSaleError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        result = LeadSerializer(lead, context=self.get_serializer_context()).data
        result["group_membership_id"] = str(membership.id) if membership else None
        return Response(
            result,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None, version=None):
        lead = self.get_object()
        changes = lead.status_changes.select_related("changed_by", "rejection_reason")
        rows = LeadStatusChangeSerializer(
            changes, many=True, context={"funnel": Funnel(lead.organization)}
        ).data
        # «Откуда» — тем же этапом, куда пришла предыдущая запись: переход
        # между своими этапами одной роли иначе читался бы «Связались →
        # Связались».
        for previous, row in zip(rows, rows[1:], strict=False):
            if row["from_status"] and row["from_status"] == previous["to_status"]:
                row["from_status_label"] = previous["to_status_label"]
        return Response(rows)

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
        if self.model is LeadRejectionReason:
            # Причины новых и продлений — разные списки (TRU-98).
            if (kind := self.request.query_params.get("kind")) in LeadKind.values:
                qs = qs.filter(kind=kind)
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


class LeadStageViewSet(TenantModelViewSet):
    """
    Этапы воронки центра (TRU-154). Читать — всем, кто работает с
    заявками; менять — владельцу и управляющему (как справочники).
    Удалить можно только этап, на котором заявок не было, — иначе скрыть;
    скрытый этап отдаёт свои заявки системному этапу той же роли.
    """

    serializer_class = LeadStageSerializer
    permission_classes = [IsAuthenticated, CanManageLeadDictionaries]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    pagination_class = None

    def get_queryset(self):
        org_stages(self.request.user.organization)  # системные этапы есть всегда
        return (
            LeadStage.objects.for_tenant(self.request.user.organization)
            .annotate(lead_count=Count("leads", filter=Q(leads__deleted_at__isnull=True)))
            .order_by("order", "created_at")
        )

    def perform_create(self, serializer):
        last = (
            LeadStage.objects.for_tenant(self.request.user.organization)
            .order_by("-order")
            .values_list("order", flat=True)
            .first()
        )
        serializer.save(organization=self.request.user.organization, order=(last or 0) + 10)

    def perform_update(self, serializer):
        was_hidden = serializer.instance.is_hidden
        stage = serializer.save()
        if stage.is_hidden and not was_hidden:
            leave_hidden_stage(stage, actor=self.request.user)

    def destroy(self, request, *args, **kwargs):
        stage = self.get_object()
        used = (
            stage.is_system
            or Lead.objects.all_with_deleted().filter(stage=stage).exists()
            or LeadStatusChange.objects.filter(to_stage=stage).exists()
        )
        if used:
            return Response(
                {"detail": "На этом этапе уже были заявки — его можно только скрыть."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        stage.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["post"])
    def reorder(self, request, version=None):
        """{ids: [...]} — новый порядок всех этапов центра."""
        stages = {str(stage.pk): stage for stage in self.get_queryset()}
        ids = [str(value) for value in request.data.get("ids") or []]
        if sorted(ids) != sorted(stages):
            return Response(
                {"detail": "Передайте все этапы воронки в новом порядке."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        for index, stage_id in enumerate(ids, start=1):
            stages[stage_id].order = index * 10
        LeadStage.objects.bulk_update(stages.values(), ["order"])
        return Response(LeadStageSerializer(self.get_queryset(), many=True).data)
