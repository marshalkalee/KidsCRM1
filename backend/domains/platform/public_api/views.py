"""Публичное API v1 (TRU-176). Объём и правила — docs/public-api.md."""

import datetime

from django.db.models import Prefetch, Q
from django.utils.dateparse import parse_date
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from domains.money.payments.models import Payment
from domains.money.subscriptions.models import Subscription
from domains.people.clients.models import Child
from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number
from domains.platform.leads.models import Lead, LeadComment, LeadSource
from domains.platform.leads.services import create_lead
from domains.platform.tenants.models import Branch, Direction
from domains.scheduling.attendance.models import Attendance
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.schedule.models import Lesson

from . import serializers as s
from .auth import ApiKeyAuthentication, HasPublicApi, PerDayThrottle, PerMinuteThrottle
from .models import ApiKey, ApiRequestLog

MAX_PERIOD_DAYS = 62
API_SOURCE = "Интеграция (API)"


class Pagination(LimitOffsetPagination):
    default_limit = 100
    max_limit = 500


class PublicApiMixin:
    """Ключ, тариф, лимиты, журнал обращений и границы ключа (организация и
    филиалы) — общие для всех маршрутов публичного API."""

    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [HasPublicApi]
    throttle_classes = [PerMinuteThrottle, PerDayThrottle]
    pagination_class = Pagination

    @property
    def key(self) -> ApiKey:
        return self.request.auth

    @property
    def organization(self):
        return self.key.organization

    def branch_ids(self):
        """Филиалы ключа; None — все филиалы центра."""
        ids = list(self.key.branches.values_list("id", flat=True))
        return ids or None

    def period(self, required=True):
        params = self.request.query_params
        start, end = (
            parse_date(params.get("date_from") or ""),
            parse_date(params.get("date_to") or ""),
        )
        if not (start and end):
            if required:
                raise ValidationError({"date_from": ["Нужны date_from и date_to (ГГГГ-ММ-ДД)."]})
            return None
        if end < start or (end - start).days > MAX_PERIOD_DAYS:
            raise ValidationError({"date_to": [f"Период — до {MAX_PERIOD_DAYS} дней."]})
        return start, end + datetime.timedelta(days=1)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        if isinstance(getattr(request, "auth", None), ApiKey):
            ApiRequestLog.objects.create(
                organization_id=request.auth.organization_id,
                key=request.auth,
                method=request.method,
                path=request.get_full_path()[:255],
                status=response.status_code,
                ip=request.META.get("REMOTE_ADDR"),
            )
        return response


def _lesson_in_branches(branch_ids, prefix=""):
    return Q(**{f"{prefix}group__branch_id__in": branch_ids}) | Q(
        **{f"{prefix}group__isnull": True, f"{prefix}room__branch_id__in": branch_ids}
    )


PERIOD = [
    OpenApiParameter("date_from", OpenApiTypes.DATE, required=True),
    OpenApiParameter("date_to", OpenApiTypes.DATE, required=True, description="Не больше 62 дней"),
]


@extend_schema(tags=["Дети"], parameters=[OpenApiParameter("status", str)])
class ChildList(PublicApiMixin, generics.ListAPIView):
    """Дети центра. В пределах филиалов ключа — те, кто занимается в их группах."""

    serializer_class = s.ChildSerializer

    def get_queryset(self):
        active = GroupMembership.objects.filter(left_at__isnull=True, deleted_at__isnull=True)
        rows = Child.objects.for_tenant(self.organization).filter(deleted_at__isnull=True)
        if ids := self.branch_ids():
            rows = rows.filter(
                group_memberships__group__branch_id__in=ids,
                group_memberships__left_at__isnull=True,
            ).distinct()
            active = active.filter(group__branch_id__in=ids)
        if value := self.request.query_params.get("status"):
            rows = rows.filter(status=value)
        return rows.order_by("full_name", "id").prefetch_related(
            Prefetch("group_memberships", queryset=active, to_attr="active_memberships")
        )


@extend_schema(tags=["Группы"])
class GroupList(PublicApiMixin, generics.ListAPIView):
    serializer_class = s.GroupSerializer

    def get_queryset(self):
        rows = Group.objects.for_tenant(self.organization).filter(deleted_at__isnull=True)
        if ids := self.branch_ids():
            rows = rows.filter(branch_id__in=ids)
        return rows.select_related("branch", "direction").order_by("name", "id")


@extend_schema(tags=["Расписание"], parameters=[*PERIOD, OpenApiParameter("group", str)])
class LessonList(PublicApiMixin, generics.ListAPIView):
    """Занятия за период (по началу занятия, UTC)."""

    serializer_class = s.LessonSerializer

    def get_queryset(self):
        start, end = self.period()
        rows = Lesson.objects.for_tenant(self.organization).filter(
            deleted_at__isnull=True, starts_at__date__gte=start, starts_at__date__lt=end
        )
        if ids := self.branch_ids():
            rows = rows.filter(_lesson_in_branches(ids))
        if value := self.request.query_params.get("group"):
            rows = rows.filter(group_id=value)
        return rows.select_related("group", "room").order_by("starts_at", "id")


@extend_schema(tags=["Посещаемость"], parameters=[*PERIOD, OpenApiParameter("child", str)])
class AttendanceList(PublicApiMixin, generics.ListAPIView):
    """Отметки посещаемости за период (по началу занятия)."""

    serializer_class = s.AttendanceSerializer

    def get_queryset(self):
        start, end = self.period()
        rows = Attendance.objects.for_tenant(self.organization).filter(
            lesson__starts_at__date__gte=start, lesson__starts_at__date__lt=end
        )
        if ids := self.branch_ids():
            rows = rows.filter(_lesson_in_branches(ids, "lesson__"))
        if value := self.request.query_params.get("child"):
            rows = rows.filter(child_id=value)
        return rows.order_by("lesson__starts_at", "id")


@extend_schema(
    tags=["Абонементы"],
    parameters=[OpenApiParameter("status", str), OpenApiParameter("child", str)],
)
class SubscriptionList(PublicApiMixin, generics.ListAPIView):
    serializer_class = s.SubscriptionSerializer

    def get_queryset(self):
        rows = Subscription.objects.for_tenant(self.organization)
        if ids := self.branch_ids():
            rows = rows.filter(branch_id__in=ids)
        if value := self.request.query_params.get("status"):
            rows = rows.filter(status=value)
        if value := self.request.query_params.get("child"):
            rows = rows.filter(child_id=value)
        return rows.select_related("subscription_type_version").order_by("-starts_on", "id")


@extend_schema(tags=["Оплаты"], parameters=[*PERIOD, OpenApiParameter("child", str)])
class PaymentList(PublicApiMixin, generics.ListAPIView):
    """Оплаты за период (по дате приёма)."""

    serializer_class = s.PaymentSerializer

    def get_queryset(self):
        start, end = self.period()
        rows = Payment.objects.for_tenant(self.organization).filter(
            paid_at__date__gte=start, paid_at__date__lt=end
        )
        if ids := self.branch_ids():
            rows = rows.filter(subscription__branch_id__in=ids)
        if value := self.request.query_params.get("child"):
            rows = rows.filter(subscription__child_id=value)
        return rows.select_related("subscription").order_by("paid_at", "id")


class LeadCreate(PublicApiMixin, APIView):
    """Новая заявка — попадает в воронку центра со статусом «Новая» и
    источником «Интеграция (API)». Нужен ключ «чтение и запись»."""

    @extend_schema(
        tags=["Заявки"],
        request=s.LeadCreateSerializer,
        responses={201: s.LeadCreatedSerializer},
    )
    def post(self, request, version=None):
        data = s.LeadCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        data = data.validated_data
        try:
            phone = normalize_phone_number(data["phone"])
        except InvalidPhoneNumberError as exc:
            raise ValidationError({"phone": ["Неверный номер телефона."]}) from exc
        branch = None
        if data["branch_id"]:
            allowed = self.branch_ids()
            if allowed is not None and data["branch_id"] not in allowed:
                raise ValidationError({"branch_id": ["Филиал недоступен этому ключу."]})
            branch = Branch.objects.filter(
                organization=self.organization, pk=data["branch_id"]
            ).first()
            if branch is None:
                raise ValidationError({"branch_id": ["Нет такого филиала."]})
        direction = None
        if data["direction_id"]:
            direction = Direction.objects.filter(
                organization=self.organization, pk=data["direction_id"]
            ).first()
            if direction is None:
                raise ValidationError({"direction_id": ["Нет такого направления."]})
        source, _ = LeadSource.objects.get_or_create(
            organization=self.organization, name=API_SOURCE, defaults={"is_active": True}
        )
        lead = create_lead(
            organization=self.organization,
            actor=None,
            kind=Lead.Kind.NEW,
            branch=branch,
            parent_name=data["parent_name"].strip(),
            phone=phone,
            child_name=data["child_name"],
            child_age=data["child_age"],
            direction=direction,
            source=source,
        )
        if data["comment"]:
            LeadComment.objects.create(
                organization=self.organization, lead=lead, author=None, text=data["comment"]
            )
        return Response({"id": str(lead.id), "status": lead.status}, status=status.HTTP_201_CREATED)
