from django.db.models import Count, Prefetch, Q
from django.utils import timezone
from rest_framework import filters, status
from rest_framework.decorators import action
from rest_framework.response import Response

from domains.platform.core.permissions import IsOwnerOrManager, IsStaffOfOrganization
from domains.platform.core.viewsets import TenantModelViewSet
from domains.scheduling.groups.models import Group

from .models import Lesson
from .serializers import LessonSerializer


class LessonViewSet(TenantModelViewSet):
    serializer_class = LessonSerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["starts_at", "status"]
    ordering = ["starts_at"]
    # Календарь читает диапазон дат целиком за один HTTP-запрос (ТЗ п. 10.2:
    # ≤ 1с при 500 занятиях в неделю) — постраничная выдача заставила бы
    # фронт делать несколько запросов на одну неделю.
    pagination_class = None

    def get_permissions(self):
        if self.action in ["create", "update", "partial_update", "destroy"]:
            return [IsOwnerOrManager()]
        return [IsStaffOfOrganization()]

    def get_queryset(self):
        groups_qs = Group.objects.select_related("direction").annotate(
            enrolled_count=Count(
                "memberships",
                filter=Q(memberships__left_at__isnull=True),
                distinct=True,
            )
        )
        # Одна выборка занятий за период + доп. выборки на все встретившиеся
        # группы и на обратную O2O rescheduled_to (иначе LessonSerializer.
        # get_rescheduled_to_id бьёт в БД на каждое занятие) — независимо
        # от числа занятий, без запроса на каждую строку.
        qs = (
            Lesson.objects.for_tenant(self.request.organization)
            .select_related("room", "teacher", "schedule_slot")
            .prefetch_related(Prefetch("group", queryset=groups_qs), "rescheduled_to")
        )

        # Фильтр по периоду
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")
        if date_from:
            qs = qs.filter(starts_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(starts_at__date__lte=date_to)

        # Фильтр по группе
        group_id = self.request.query_params.get("group")
        if group_id:
            qs = qs.filter(group_id=group_id)

        # Фильтр по преподавателю
        teacher_id = self.request.query_params.get("teacher")
        if teacher_id:
            qs = qs.filter(teacher_id=teacher_id)

        # Фильтр по филиалу
        branch_id = self.request.query_params.get("branch")
        if branch_id:
            qs = qs.filter(group__branch_id=branch_id)

        # Фильтр по статусу
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        # Занятия сегодня в зоне организации
        if self.request.query_params.get("today"):
            org = self.request.organization
            tz = timezone.zoneinfo.ZoneInfo(org.timezone or "Asia/Almaty")
            today = timezone.now().astimezone(tz).date()
            qs = qs.filter(starts_at__date=today)

        return qs

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        lesson = self.get_object()
        reason = request.data.get("reason", "")
        try:
            lesson.transition_to(Lesson.Status.CANCELLED)
            lesson.cancel_reason = reason
            lesson.is_modified = True
            lesson.save(update_fields=["cancel_reason", "is_modified", "updated_at"])
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(LessonSerializer(lesson, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        lesson = self.get_object()
        try:
            lesson.transition_to(Lesson.Status.COMPLETED)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(LessonSerializer(lesson, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def reschedule(self, request, pk=None):
        """
        Перенос занятия — создаёт новое занятие и связывает с текущим.
        """
        lesson = self.get_object()
        serializer = LessonSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        new_lesson = serializer.save(
            organization=self.request.organization,
            is_modified=True,
        )
        try:
            lesson.reschedule_to(new_lesson)
        except Exception as e:
            new_lesson.delete()
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            LessonSerializer(new_lesson, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )
