from django.db.models import Count, Prefetch, Q
from django.utils import timezone
from rest_framework import filters, status
from rest_framework.decorators import action
from rest_framework.response import Response

from domains.platform.core.permissions import IsOwnerOrManager, IsStaffOfOrganization
from domains.platform.core.viewsets import TenantModelViewSet
from domains.scheduling.groups.models import Group

from .conflicts import compute_conflict_map, find_conflicting_lessons
from .models import Lesson
from .serializers import LessonSerializer


def _is_confirmed(request):
    # Фронт шлёт confirm_conflict: true вторым запросом после того, как
    # администратор увидел предупреждение и подтвердил сохранение (ТЗ п.
    # 4.2: предупреждение, не запрет). Строка "true"/"1" — на случай
    # multipart/form-data, где всё приходит строками.
    value = request.data.get("confirm_conflict")
    return value in (True, "true", "1", 1)


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

        # Фильтр по преподавателю — сам преподаватель не может им себя
        # расширить на чужие занятия, см. принудительный скоуп ниже.
        user = self.request.user
        teacher_id = self.request.query_params.get("teacher")
        if teacher_id and user.role != "teacher":
            qs = qs.filter(teacher_id=teacher_id)

        # Фильтр по филиалу — у занятия нет своего branch, берём либо из
        # группы, либо (для индивидуальных занятий без группы) из зала.
        branch_id = self.request.query_params.get("branch")
        if branch_id:
            qs = qs.filter(Q(group__branch_id=branch_id) | Q(room__branch_id=branch_id))

        # Фильтр по залу (TRU-45: дневной вид по залам)
        room_id = self.request.query_params.get("room")
        if room_id:
            qs = qs.filter(room_id=room_id)

        # Фильтр по направлению (TRU-45)
        direction_id = self.request.query_params.get("direction")
        if direction_id:
            qs = qs.filter(group__direction_id=direction_id)

        # Фильтр по статусу
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        # Преподаватель видит только свои занятия (ТЗ п. 2, TRU-19) —
        # экран календаря должен открываться сразу в этом виде, без
        # необходимости фильтровать самому (TRU-45). Та же схема, что и
        # в groups.views.GroupViewSet.get_queryset.
        if user.role == "teacher":
            qs = qs.filter(teacher=user)

        # Занятия сегодня в зоне организации
        if self.request.query_params.get("today"):
            org = self.request.organization
            tz = timezone.zoneinfo.ZoneInfo(org.timezone or "Asia/Almaty")
            today = timezone.now().astimezone(tz).date()
            qs = qs.filter(starts_at__date=today)

        return qs

    def list(self, request, *args, **kwargs):
        # Конфликты считаются один раз на всё уже загруженное окно (TRU-46)
        # — без доп. запросов на занятие, видно прямо в календаре, не
        # только в момент создания (критерий приёмки).
        lessons = list(self.filter_queryset(self.get_queryset()))
        conflict_map = compute_conflict_map(lessons)
        context = self.get_serializer_context()
        context["conflict_map"] = conflict_map
        serializer = self.get_serializer(lessons, many=True, context=context)
        return Response(serializer.data)

    def _conflict_response(self, conflicts):
        context = self.get_serializer_context()
        return Response(
            {
                "conflict": True,
                "detail": "Пересекается по залу или преподавателю с другим занятием. "
                "Отправьте confirm_conflict: true, чтобы сохранить всё равно.",
                "conflicts": LessonSerializer(conflicts, many=True, context=context).data,
            },
            status=status.HTTP_409_CONFLICT,
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data.get("status", Lesson.Status.SCHEDULED) != Lesson.Status.CANCELLED:
            conflicts = find_conflicting_lessons(
                self.request.organization,
                starts_at=data["starts_at"],
                ends_at=data["ends_at"],
                room=data.get("room"),
                teacher=data.get("teacher"),
            )
            if conflicts.exists() and not _is_confirmed(request):
                return self._conflict_response(conflicts)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        starts_at = data.get("starts_at", instance.starts_at)
        ends_at = data.get("ends_at", instance.ends_at)
        room = data.get("room", instance.room)
        teacher = data.get("teacher", instance.teacher)
        new_status = data.get("status", instance.status)
        if new_status != Lesson.Status.CANCELLED:
            conflicts = find_conflicting_lessons(
                self.request.organization,
                starts_at=starts_at,
                ends_at=ends_at,
                room=room,
                teacher=teacher,
                exclude_id=instance.id,
            )
            if conflicts.exists() and not _is_confirmed(request):
                return self._conflict_response(conflicts)
        self.perform_update(serializer)
        return Response(serializer.data)

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
        data = serializer.validated_data
        conflicts = find_conflicting_lessons(
            self.request.organization,
            starts_at=data["starts_at"],
            ends_at=data["ends_at"],
            room=data.get("room"),
            teacher=data.get("teacher"),
        )
        if conflicts.exists() and not _is_confirmed(request):
            return self._conflict_response(conflicts)

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

    @action(detail=False, methods=["get"])
    def conflicts(self, request):
        """
        Отдельный список текущих конфликтов (ТЗ п. 4.2, TRU-46) — чтобы
        администратор мог разобрать их разом, а не натыкаться по одному в
        календаре. По умолчанию — незавершённые занятия от сегодня и
        дальше (то, что реально можно ещё разрулить); те же query-фильтры
        (branch/room/teacher/direction), что и у списка календаря.
        """
        qs = self.filter_queryset(self.get_queryset())
        if not request.query_params.get("date_from"):
            org = self.request.organization
            tz = timezone.zoneinfo.ZoneInfo(org.timezone or "Asia/Almaty")
            today = timezone.now().astimezone(tz).date()
            qs = qs.filter(starts_at__date__gte=today)
        if not request.query_params.get("status"):
            qs = qs.exclude(status=Lesson.Status.CANCELLED)

        lessons = list(qs)
        conflict_map = compute_conflict_map(lessons)
        conflicting = [lesson for lesson in lessons if lesson.id in conflict_map]

        context = self.get_serializer_context()
        context["conflict_map"] = conflict_map
        serializer = LessonSerializer(conflicting, many=True, context=context)
        return Response(serializer.data)
