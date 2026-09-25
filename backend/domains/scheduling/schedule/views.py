from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from domains.people.clients.models import ChildContact, CommunicationLog, ParentContact
from domains.platform.core.permissions import IsOwnerOrManager, IsStaffOfOrganization
from domains.platform.core.viewsets import TenantModelViewSet
from domains.scheduling.groups.models import Group

from .conflicts import compute_conflict_map, find_conflicting_lessons
from .enrollment_service import EnrollOutcome, LessonService
from .models import Lesson, LessonEnrollment, RescheduleCallLog
from .reschedule_contacts import build_reschedule_message, build_who_to_call
from .serializers import LessonEnrollmentSerializer, LessonEnrollSerializer, LessonSerializer


def _is_confirmed(request):
    # Фронт шлёт confirm_conflict: true вторым запросом после того, как
    # администратор увидел предупреждение и подтвердил сохранение (ТЗ п.
    # 4.2: предупреждение, не запрет). Строка "true"/"1" — на случай
    # multipart/form-data, где всё приходит строками.
    value = request.data.get("confirm_conflict")
    return value in (True, "true", "1", 1)


def _cancel_reason_from_request(request):
    """TRU-48: отмена без причины из справочника невозможна на уровне API
    (критерий приёмки). category — обязателен всегда; comment — обязателен
    только для category=OTHER (для остальных категорий сама категория уже
    достаточно информативна)."""
    category = request.data.get("reason_category", "")
    comment = request.data.get("comment", "")
    valid = {value for value, _ in Lesson.CancelReasonCategory.choices}
    if category not in valid:
        raise DRFValidationError(
            {"reason_category": f"Укажите причину отмены — одну из: {', '.join(sorted(valid))}."}
        )
    if category == Lesson.CancelReasonCategory.OTHER and not comment.strip():
        raise DRFValidationError({"comment": "Для причины «Другое» нужен комментарий."})
    return category, comment


def _is_confirmed(request):
    # Фронт шлёт confirm_conflict: true вторым запросом после того, как
    # администратор увидел предупреждение и подтвердил сохранение (ТЗ п.
    # 4.2: предупреждение, не запрет). Строка "true"/"1" — на случай
    # multipart/form-data, где всё приходит строками.
    value = request.data.get("confirm_conflict")
    return value in (True, "true", "1", 1)


def _cancel_reason_from_request(request):
    """TRU-48: отмена без причины из справочника невозможна на уровне API
    (критерий приёмки). category — обязателен всегда; comment — обязателен
    только для category=OTHER (для остальных категорий сама категория уже
    достаточно информативна)."""
    category = request.data.get("reason_category", "")
    comment = request.data.get("comment", "")
    valid = {value for value, _ in Lesson.CancelReasonCategory.choices}
    if category not in valid:
        raise DRFValidationError(
            {"reason_category": f"Укажите причину отмены — одну из: {', '.join(sorted(valid))}."}
        )
    if category == Lesson.CancelReasonCategory.OTHER and not comment.strip():
        raise DRFValidationError({"comment": "Для причины «Другое» нужен комментарий."})
    return category, comment


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
        if self.action in ["create", "update", "partial_update", "destroy", "bulk_cancel"]:
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
        # группы, обратную O2O rescheduled_to (иначе LessonSerializer.
        # get_rescheduled_to_id бьёт в БД на каждое занятие) и детей
        # индивидуальных занятий (TRU-47) — независимо от числа занятий,
        # без запроса на каждую строку.
        qs = (
            Lesson.objects.for_tenant(self.request.organization)
            .select_related("room", "teacher", "schedule_slot")
            .prefetch_related(
                Prefetch("group", queryset=groups_qs), "rescheduled_to", "individual_children"
            )
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
        try:
            category, comment = _cancel_reason_from_request(request)
        except DRFValidationError as e:
            return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)
        try:
            lesson.cancel(actor=request.user, category=category, comment=comment)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(LessonSerializer(lesson, context={"request": request}).data)

    @action(detail=False, methods=["post"])
    def bulk_cancel(self, request):
        """
        Массовая отмена за период (ТЗ п. 4.2) — каникулы/праздники, пока
        нет отдельного календаря исключений. Отменяет только запланированные
        занятия (уже отменённые/проведённые/перенесённые не трогает) в
        [date_from, date_to] включительно; необязательные branch/room/
        teacher/group/direction сужают охват — например, отменить занятия
        только одного преподавателя (заболел), а не весь филиал.
        """
        date_from = request.data.get("date_from")
        date_to = request.data.get("date_to")
        if not date_from or not date_to:
            return Response(
                {"detail": "date_from и date_to обязательны."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            category, comment = _cancel_reason_from_request(request)
        except DRFValidationError as e:
            return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)

        qs = self.get_queryset().filter(
            starts_at__date__gte=date_from,
            starts_at__date__lte=date_to,
            status=Lesson.Status.SCHEDULED,
        )
        branch_id = request.data.get("branch")
        if branch_id:
            qs = qs.filter(Q(group__branch_id=branch_id) | Q(room__branch_id=branch_id))
        direction_id = request.data.get("direction")
        if direction_id:
            qs = qs.filter(group__direction_id=direction_id)
        for field in ("room", "teacher", "group"):
            value = request.data.get(field)
            if value:
                qs = qs.filter(**{f"{field}_id": value})

        lessons = list(qs)
        for lesson in lessons:
            lesson.cancel(actor=request.user, category=category, comment=comment)

        return Response(
            {
                "cancelled_count": len(lessons),
                "lesson_ids": [str(lesson.id) for lesson in lessons],
            }
        )

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
            lesson.reschedule_to(new_lesson, actor=request.user)
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

    @action(detail=True, methods=["get"], url_path="who-to-call")
    def who_to_call(self, request, pk=None):
        """
        TRU-49: список контактов для обзвона о переносе — исходное
        (перенесённое) занятие, pk. Готовый текст сообщения и wa.me-ссылка
        с уже подставленным текстом (ТЗ п. 4.5); кто уже обзвонён —
        RescheduleCallLog, сохраняется между заходами на экран.
        """
        lesson = self.get_object()
        if lesson.status != Lesson.Status.RESCHEDULED or not hasattr(lesson, "rescheduled_to"):
            return Response(
                {"detail": "Занятие не перенесено — обзванивать не о чем."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = build_who_to_call(lesson, self.request.organization)
        return Response(data)

    @action(detail=True, methods=["post"], url_path="mark-called")
    def mark_called(self, request, pk=None):
        """
        Отметка «обзвонил» — сохраняется (не только на фронте, критерий
        приёмки TRU-49) и пишет факт в CommunicationLog каждого затронутого
        ребёнка этого контакта (вкладка «Коммуникации», TRU-28). Повторная
        отметка того же контакта по тому же занятию — идемпотентна, не
        плодит вторую запись коммуникации.
        """
        lesson = self.get_object()
        if lesson.status != Lesson.Status.RESCHEDULED or not hasattr(lesson, "rescheduled_to"):
            return Response(
                {"detail": "Занятие не перенесено — обзванивать не о чем."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        contact_id = request.data.get("parent_contact")
        if not contact_id:
            return Response({"parent_contact": "Обязателен."}, status=status.HTTP_400_BAD_REQUEST)
        parent_contact = get_object_or_404(
            ParentContact.objects.for_tenant(self.request.organization), pk=contact_id
        )
        channel = request.data.get("channel", CommunicationLog.Channel.CALL)
        valid_channels = {value for value, _ in CommunicationLog.Channel.choices}
        if channel not in valid_channels:
            channel = CommunicationLog.Channel.CALL

        _call_log, created = RescheduleCallLog.objects.get_or_create(
            lesson=lesson, parent_contact=parent_contact, defaults={"called_by": request.user}
        )
        if created:
            tz = timezone.zoneinfo.ZoneInfo(self.request.organization.timezone or "Asia/Almaty")
            message = build_reschedule_message(lesson, lesson.rescheduled_to, tz)
            child_ids = {child.id for child in lesson.participants()}
            affected_child_ids = (
                ChildContact.objects.for_tenant(self.request.organization)
                .filter(parent_contact=parent_contact, child_id__in=child_ids)
                .values_list("child_id", flat=True)
                .distinct()
            )
            for child_id in affected_child_ids:
                CommunicationLog.objects.create(
                    child_id=child_id,
                    parent_contact=parent_contact,
                    channel=channel,
                    note=f"Обзвон о переносе занятия. {message}",
                    author=request.user,
                )
        return Response({"called": True})

    @action(detail=True, methods=["post"], url_path="unmark-called")
    def unmark_called(self, request, pk=None):
        """Снять отметку (передумали/ошиблись контактом) — историю
        CommunicationLog не трогает, тот лог append-only."""
        lesson = self.get_object()
        contact_id = request.data.get("parent_contact")
        RescheduleCallLog.objects.filter(lesson=lesson, parent_contact_id=contact_id).delete()
        return Response({"called": False})


_ENROLL_ERROR_STATUS = {
    EnrollOutcome.ALREADY_ENROLLED: (
        status.HTTP_400_BAD_REQUEST,
        "Ребёнок уже записан на это занятие.",
    ),
    EnrollOutcome.LESSON_CANCELLED: (
        status.HTTP_400_BAD_REQUEST,
        "Занятие отменено или перенесено.",
    ),
    EnrollOutcome.LESSON_IN_PAST: (status.HTTP_400_BAD_REQUEST, "Занятие уже прошло."),
}


class LessonEnrollmentViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Запись «поверх» группы (TRU-53) — отработки (M1) и пробные (M2).
    Создание и отмена — не обычные create/destroy DRF, а вызов
    LessonService (контроль вместимости, аудит, правило списания);
    обычный POST/DELETE позволил бы это обойти."""

    serializer_class = LessonEnrollmentSerializer
    permission_classes = [IsAuthenticated, IsStaffOfOrganization]

    def get_permissions(self):
        if self.action in ["create", "cancel"]:
            return [IsOwnerOrManager()]
        return [IsStaffOfOrganization()]

    def get_queryset(self):
        qs = LessonEnrollment.objects.for_tenant(self.request.organization).select_related(
            "child", "lesson", "enrolled_by"
        )
        lesson_id = self.request.query_params.get("lesson")
        if lesson_id:
            qs = qs.filter(lesson_id=lesson_id)
        return qs

    def create(self, request, *args, **kwargs):
        serializer = LessonEnrollSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        result = LessonService.enroll(
            data["lesson"].id,
            data["child"].id,
            data["kind"],
            actor=request.user,
            confirm_capacity=data["confirm_capacity"],
        )

        if result.outcome == EnrollOutcome.CAPACITY_EXCEEDED:
            return Response(
                {
                    "detail": "Вместимость группы превышена. Отправьте confirm_capacity: true, "
                    "чтобы записать всё равно.",
                    "capacity": result.capacity,
                    "current_count": result.current_count,
                },
                status=status.HTTP_409_CONFLICT,
            )
        if result.outcome in _ENROLL_ERROR_STATUS:
            code, detail = _ENROLL_ERROR_STATUS[result.outcome]
            return Response({"detail": detail}, status=code)

        enrollment = LessonEnrollment.objects.get(id=result.enrollment_id)
        return Response(
            LessonEnrollmentSerializer(enrollment, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        enrollment = self.get_object()
        LessonService.cancel_enrollment(enrollment.id, actor=request.user)
        enrollment.refresh_from_db()
        return Response(LessonEnrollmentSerializer(enrollment, context={"request": request}).data)
