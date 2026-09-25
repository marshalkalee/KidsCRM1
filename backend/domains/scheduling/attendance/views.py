import datetime

from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from domains.platform.core.permissions import IsStaffOfOrganization
from domains.scheduling.schedule.enrollment_service import (
    available_makeups_for_child,
    makeup_candidate_lessons,
)
from domains.scheduling.schedule.models import Lesson, LessonEnrollment
from domains.scheduling.schedule.serializers import (
    AvailableMakeupSerializer,
    MakeupCandidateSerializer,
)

from .models import Attendance
from .serializers import (
    AttendanceMarkSerializer,
    AttendanceRosterEntrySerializer,
    AttendanceSerializer,
)


def _get_lesson_scoped(request, lesson_id):
    """TRU-56, RBAC: преподаватель отмечает только свои занятия — та же
    проверка роли, что в LessonViewSet.get_queryset для календаря, только
    здесь по одному конкретному занятию (roster/mark-all-present берут
    lesson_id из query/body, а не из URL detail-маршрута)."""
    try:
        lesson = Lesson.objects.for_tenant(request.organization).get(pk=lesson_id)
    except (Lesson.DoesNotExist, ValueError, TypeError) as exc:
        raise NotFound("Занятие не найдено.") from exc
    if request.user.role == "teacher" and lesson.teacher_id != request.user.id:
        raise PermissionDenied("Доступно только для своих занятий.")
    return lesson


class AttendanceViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Только чтение + два входа на запись — `mark` (одно занятие × один
    ребёнок) и `mark_all_present` (пачкой). Обычные create/update здесь
    намеренно не открыты: они позволили бы сменить status в обход
    Attendance.mark() и разошлись бы со списанием с абонемента
    (SubscriptionService не был бы вызван)."""

    serializer_class = AttendanceSerializer
    permission_classes = [IsAuthenticated, IsStaffOfOrganization]

    def get_queryset(self):
        qs = Attendance.objects.for_tenant(self.request.organization).select_related(
            "child", "lesson", "marked_by"
        )
        lesson_id = self.request.query_params.get("lesson")
        if lesson_id:
            qs = qs.filter(lesson_id=lesson_id)
        child_id = self.request.query_params.get("child")
        if child_id:
            qs = qs.filter(child_id=child_id)
        return qs

    @action(detail=False, methods=["post"])
    def mark(self, request):
        serializer = AttendanceMarkSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        lesson = serializer.validated_data["lesson"]
        child = serializer.validated_data["child"]
        status_value = serializer.validated_data["status"]
        absence_reason = serializer.validated_data.get("absence_reason", "")

        if request.user.role == "teacher" and lesson.teacher_id != request.user.id:
            raise PermissionDenied("Доступно только для своих занятий.")

        attendance, _created = Attendance.objects.get_or_create(
            lesson=lesson,
            child=child,
            defaults={
                "organization": self.request.organization,
                "status": Attendance.Status.ABSENT,
            },
        )
        attendance.mark(status_value, actor=request.user, absence_reason=absence_reason)
        return Response(AttendanceSerializer(attendance, context={"request": request}).data)

    @action(detail=False, methods=["get"])
    def roster(self, request):
        """TRU-56: список детей занятия для экрана отметки — состав группы
        на дату занятия (либо individual_children для индивидуального,
        Lesson.participants() уже унифицирует), каждый со своей текущей
        отметкой, если она уже есть (повторное открытие показывает
        проставленное — критерий приёмки). Ребёнок без записи Attendance —
        `attendance: null`, "не отмечен", это не то же самое, что «не был»."""
        lesson_id = request.query_params.get("lesson")
        if not lesson_id:
            raise ValidationError({"lesson": "Обязателен."})
        lesson = _get_lesson_scoped(request, lesson_id)

        participants = list(lesson.participants().order_by("full_name"))
        attendances = {
            a.child_id: a
            for a in Attendance.objects.for_tenant(request.organization).filter(
                lesson=lesson, child__in=participants
            )
        }
        # TRU-53: записанные «поверх» группы (отработка/пробное) видны в
        # ростере с пометкой типа — тот же список участников (уже
        # включает их, см. Lesson.participants), плюс их kind отдельно.
        enrollment_kinds = dict(
            LessonEnrollment.objects.for_tenant(request.organization)
            .filter(lesson=lesson, cancelled_at__isnull=True, child__in=participants)
            .values_list("child_id", "kind")
        )
        entries = [
            {
                "child": child,
                "attendance": attendances.get(child.id),
                "enrollment_kind": enrollment_kinds.get(child.id),
            }
            for child in participants
        ]
        data = AttendanceRosterEntrySerializer(
            entries, many=True, context={"request": request}
        ).data
        return Response(
            {
                "lesson": str(lesson.id),
                "lesson_status": lesson.status,
                "participants_count": len(participants),
                "marked_count": len(attendances),
                "results": data,
            }
        )

    @action(detail=False, methods=["post"], url_path="mark-all-present")
    def mark_all_present(self, request):
        """«Отметить всех пришедшими» — почти всегда приходят почти все,
        отмечать каждого вручную бессмысленно. Трогает только тех, кого ещё
        никак не отмечали (нет записи Attendance) — уже проставленные
        (в т.ч. «не был») не перезаписывает, чтобы не затирать ручную
        работу администратора одной кнопкой."""
        lesson_id = request.data.get("lesson")
        if not lesson_id:
            raise ValidationError({"lesson": "Обязателен."})
        lesson = _get_lesson_scoped(request, lesson_id)

        participants = list(lesson.participants())
        already_marked = set(
            Attendance.objects.for_tenant(request.organization)
            .filter(lesson=lesson, child__in=participants)
            .values_list("child_id", flat=True)
        )
        marked = []
        for child in participants:
            if child.id in already_marked:
                continue
            attendance = Attendance.objects.create(
                organization=request.organization,
                lesson=lesson,
                child=child,
                status=Attendance.Status.ABSENT,
            )
            attendance.mark(Attendance.Status.PRESENT, actor=request.user)
            marked.append(attendance)

        return Response(
            {
                "marked_count": len(marked),
                "results": AttendanceSerializer(
                    marked, many=True, context={"request": request}
                ).data,
            }
        )

    @action(detail=False, methods=["get"], url_path="unmarked-yesterday")
    def unmarked_yesterday(self, request):
        """TRU-52, ТЗ п. 4.5: вчерашние занятия, посещаемость по которым
        отмечена не полностью (в т.ч. вообще не отмечена) — сырая выборка
        для центра уведомлений сотруднику (TRU-72, делает Bekzat). Здесь
        только отдаём данные, само уведомление — не наша часть. Учитель
        видит только свои занятия — тот же принцип RBAC, что и в roster."""
        tz = timezone.zoneinfo.ZoneInfo(request.organization.timezone or "Asia/Almaty")
        yesterday = (timezone.now().astimezone(tz) - datetime.timedelta(days=1)).date()

        lessons = (
            Lesson.objects.for_tenant(request.organization)
            .exclude(status__in=[Lesson.Status.CANCELLED, Lesson.Status.RESCHEDULED])
            .filter(starts_at__date=yesterday)
            .select_related("group", "room", "teacher")
        )
        if request.user.role == "teacher":
            lessons = lessons.filter(teacher=request.user)

        results = []
        for lesson in lessons:
            participants = list(lesson.participants())
            if not participants:
                continue
            marked_count = (
                Attendance.objects.for_tenant(request.organization)
                .filter(lesson=lesson, child__in=participants)
                .count()
            )
            if marked_count < len(participants):
                results.append(
                    {
                        "lesson": str(lesson.id),
                        "group_name": lesson.group.name if lesson.group else None,
                        "room_name": lesson.room.name if lesson.room else None,
                        "teacher_id": str(lesson.teacher_id) if lesson.teacher_id else None,
                        "starts_at": lesson.starts_at.isoformat(),
                        "participants_count": len(participants),
                        "marked_count": marked_count,
                    }
                )
        return Response({"date": yesterday.isoformat(), "results": results})

    @action(detail=False, methods=["get"], url_path="available-makeups")
    def available_makeups(self, request):
        """TRU-54: пропуски ребёнка, доступные для отработки (карточка
        ребёнка) — не использованы и не сгорели (MAKEUP_EXPIRY_DAYS)."""
        child_id = request.query_params.get("child")
        if not child_id:
            raise ValidationError({"child": "Обязателен."})
        rows = available_makeups_for_child(request.organization, child_id)
        data = AvailableMakeupSerializer(rows, many=True, context={"request": request}).data
        return Response({"results": data})

    @action(detail=True, methods=["get"], url_path="makeup-candidates")
    def makeup_candidates(self, request, pk=None):
        """TRU-54: занятия-кандидаты для отработки конкретного пропуска —
        то же направление, ещё не наступившие. pk — id Attendance
        (пропущенного занятия), не Lesson."""
        attendance = self.get_object()
        if attendance.status != Attendance.Status.ABSENT:
            raise ValidationError({"detail": "Это занятие не помечено как пропущенное."})
        candidates = makeup_candidate_lessons(attendance, request.organization)
        data = MakeupCandidateSerializer(candidates, many=True, context={"request": request}).data
        return Response({"results": data})
