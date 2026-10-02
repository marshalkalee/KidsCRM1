"""API кабинета родителя: /api/v1/portal/ (TRU-135)."""

import datetime

from django.db.models import Prefetch, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from domains.scheduling.attendance.history import (
    attendance_history_queryset,
    attendance_history_summary,
)
from domains.scheduling.attendance.models import Attendance
from domains.scheduling.schedule.enrollment_service import (
    EnrollOutcome,
    LessonService,
    available_makeups_for_child,
    makeup_candidate_lessons,
)
from domains.scheduling.schedule.models import Lesson, LessonEnrollment

from . import access, account
from .auth import LoginError, logout, request_code, verify_code
from .authentication import IsParent, ParentTokenAuthentication, request_meta
from .models import ParentSession
from .serializers import (
    AttendancePeriodSerializer,
    ParentAttendanceSerializer,
    ParentAvailableMakeupSerializer,
    ParentLessonSerializer,
    ParentMakeupBookingSerializer,
    ParentMakeupCandidateSerializer,
)


def _error(exc: LoginError):
    response = Response({"detail": str(exc)}, status=exc.status)
    if exc.retry_after:
        response["Retry-After"] = str(exc.retry_after)
    return response


class PublicView(APIView):
    # Без токена: старый JWT сотрудника или протухший токен родителя в
    # браузере не должен ронять вход.
    authentication_classes = []
    permission_classes = [AllowAny]


class RequestCodeView(PublicView):
    def post(self, request, version=None):
        try:
            return Response(request_code(request.data.get("phone", ""), request_meta(request)))
        except LoginError as exc:
            return _error(exc)


class VerifyCodeView(PublicView):
    def post(self, request, version=None):
        try:
            return Response(
                verify_code(
                    request.data.get("phone", ""),
                    request.data.get("code", ""),
                    request_meta(request),
                )
            )
        except LoginError as exc:
            return _error(exc)


class ParentView(APIView):
    authentication_classes = [ParentTokenAuthentication]
    permission_classes = [IsParent]


class LogoutView(ParentView):
    def post(self, request, version=None):
        logout(request.auth, request_meta(request), everywhere=bool(request.data.get("everywhere")))
        return Response(status=status.HTTP_204_NO_CONTENT)


class SessionsView(ParentView):
    """Устройства, где родитель вошёл, — чтобы отозвать потерянный телефон."""

    def get(self, request, version=None):
        rows = ParentSession.objects.filter(account=request.user, revoked_at__isnull=True)
        return Response(
            [
                {
                    "id": str(s.id),
                    "user_agent": s.user_agent,
                    "created_at": s.created_at,
                    "last_seen_at": s.last_seen_at,
                    "current": s.pk == request.auth.pk,
                }
                for s in rows
            ]
        )


class SessionDetailView(ParentView):
    def delete(self, request, session_id, version=None):
        from django.utils import timezone

        updated = ParentSession.objects.filter(
            account=request.user, pk=session_id, revoked_at__isnull=True
        ).update(revoked_at=timezone.now())
        if not updated:
            return Response({"detail": "Не найдено."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(ParentView):
    """Кто вошёл, его профиль и все его дети — первый запрос кабинета."""

    def get(self, request, version=None):
        return Response(
            {**account.profile(request.user), "children": account.children(request.user)}
        )


class ChildDetailView(ParentView):
    """Один ребёнок родителя. Чужой и несуществующий — одинаково 404."""

    def get(self, request, child_id, version=None):
        for child in account.children(request.user):
            if child["id"] == str(child_id):
                return Response(child)
        return Response({"detail": "Не найдено."}, status=status.HTTP_404_NOT_FOUND)


class ChildAttendanceView(ParentView):
    """Attendance history for one child visible to the signed-in parent (TRU-142)."""

    def get(self, request, child_id, version=None):
        child = access.child_for_phone(request.user.phone, child_id)
        if child is None:
            return Response({"detail": "Не найдено."}, status=status.HTTP_404_NOT_FOUND)

        query = AttendancePeriodSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        date_from = query.validated_data.get("date_from")
        date_to = query.validated_data.get("date_to")
        history = attendance_history_queryset(
            child.organization,
            child.id,
            date_from=date_from,
            date_to=date_to,
        )
        makeups = available_makeups_for_child(child.organization, child.id)
        context = {"organization": child.organization}
        return Response(
            {
                "period": {"date_from": date_from, "date_to": date_to},
                "summary": attendance_history_summary(history),
                "results": ParentAttendanceSerializer(history, many=True, context=context).data,
                "available_makeups": ParentAvailableMakeupSerializer(
                    makeups, many=True, context=context
                ).data,
            }
        )


class ChildScheduleView(ParentView):
    """Upcoming group, individual and extra lessons for a parent's child."""

    def get(self, request, child_id, version=None):
        child = access.child_for_phone(request.user.phone, child_id)
        if child is None:
            return Response({"detail": "Не найдено."}, status=status.HTTP_404_NOT_FOUND)

        query = AttendancePeriodSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        organization = child.organization
        tz = timezone.zoneinfo.ZoneInfo(organization.timezone or "Asia/Almaty")
        today = timezone.now().astimezone(tz).date()
        date_from = query.validated_data.get("date_from") or today
        date_to = query.validated_data.get("date_to") or (date_from + datetime.timedelta(days=60))

        starts_at = datetime.datetime.combine(date_from, datetime.time.min, tzinfo=tz)
        ends_at = datetime.datetime.combine(
            date_to + datetime.timedelta(days=1), datetime.time.min, tzinfo=tz
        )
        participation = (
            (
                Q(
                    group__memberships__child=child,
                    group__memberships__deleted_at__isnull=True,
                    group__memberships__joined_at__lte=date_to,
                )
                & (
                    Q(group__memberships__left_at__isnull=True)
                    | Q(group__memberships__left_at__gte=date_from)
                )
            )
            | Q(individual_children=child)
            | Q(
                enrollments__child=child,
                enrollments__cancelled_at__isnull=True,
            )
        )
        lessons = (
            Lesson.objects.filter(
                organization=organization,
                starts_at__gte=starts_at,
                starts_at__lt=ends_at,
            )
            .filter(participation)
            .exclude(status=Lesson.Status.RESCHEDULED)
            .select_related("group__direction", "group__branch", "room", "teacher")
            .prefetch_related(
                Prefetch(
                    "enrollments",
                    queryset=LessonEnrollment.objects.filter(
                        child=child, cancelled_at__isnull=True
                    ),
                    to_attr="parent_enrollments",
                )
            )
            .distinct()
            .order_by("starts_at")
        )
        return Response(
            {
                "period": {"date_from": date_from, "date_to": date_to},
                "results": ParentLessonSerializer(
                    lessons, many=True, context={"organization": organization}
                ).data,
            }
        )


class ChildMakeupView(ParentView):
    """Choose and book a valid makeup lesson for one missed attendance."""

    def _source(self, request, child, attendance_id):
        attendance = (
            Attendance.objects.filter(
                organization=child.organization,
                child=child,
                id=attendance_id,
                status=Attendance.Status.ABSENT,
            )
            .select_related("lesson__group__direction")
            .first()
        )
        if attendance is None:
            return None
        available_ids = {
            row["attendance"].id
            for row in available_makeups_for_child(child.organization, child.id)
        }
        return attendance if attendance.id in available_ids else None

    def _candidates(self, child, attendance):
        candidates = makeup_candidate_lessons(attendance, child.organization)
        return [
            lesson
            for lesson in candidates
            if not lesson.participants().filter(pk=child.id).exists()
            and lesson.participants().count() < lesson.group.capacity
        ]

    def get(self, request, child_id, attendance_id, version=None):
        child = access.child_for_phone(request.user.phone, child_id)
        if child is None:
            return Response({"detail": "Не найдено."}, status=status.HTTP_404_NOT_FOUND)
        attendance = self._source(request, child, attendance_id)
        if attendance is None:
            return Response(
                {"detail": "Эта отработка уже использована или срок её действия истёк."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            {
                "attendance_id": attendance.id,
                "expires_on": next(
                    row["expires_on"]
                    for row in available_makeups_for_child(child.organization, child.id)
                    if row["attendance"].id == attendance.id
                ),
                "results": ParentMakeupCandidateSerializer(
                    self._candidates(child, attendance),
                    many=True,
                    context={"organization": child.organization},
                ).data,
            }
        )

    def post(self, request, child_id, attendance_id, version=None):
        child = access.child_for_phone(request.user.phone, child_id)
        if child is None:
            return Response({"detail": "Не найдено."}, status=status.HTTP_404_NOT_FOUND)
        attendance = self._source(request, child, attendance_id)
        if attendance is None:
            return Response(
                {"detail": "Эта отработка уже использована или срок её действия истёк."},
                status=status.HTTP_409_CONFLICT,
            )
        payload = ParentMakeupBookingSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        candidate_ids = {lesson.id for lesson in self._candidates(child, attendance)}
        lesson_id = payload.validated_data["lesson_id"]
        if lesson_id not in candidate_ids:
            return Response(
                {"detail": "Это занятие недоступно для выбранной отработки."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = LessonService.enroll(
            lesson_id,
            child.id,
            LessonEnrollment.Kind.MAKEUP,
            actor=None,
            source_attendance_id=attendance.id,
        )
        if result.outcome == EnrollOutcome.ENROLLED:
            return Response(
                {"status": "enrolled", "enrollment_id": result.enrollment_id},
                status=status.HTTP_201_CREATED,
            )
        errors = {
            EnrollOutcome.CAPACITY_EXCEEDED: "Свободных мест уже нет.",
            EnrollOutcome.SOURCE_ALREADY_USED: "Эта отработка уже использована.",
            EnrollOutcome.SOURCE_EXPIRED: "Срок этой отработки истёк.",
            EnrollOutcome.LESSON_CANCELLED: "Занятие отменено.",
            EnrollOutcome.LESSON_IN_PAST: "Занятие уже прошло.",
        }
        return Response(
            {"detail": errors.get(result.outcome, "Не удалось записаться на это занятие.")},
            status=status.HTTP_409_CONFLICT,
        )


class ProfileView(ParentView):
    def get(self, request, version=None):
        return Response(account.profile(request.user))

    def patch(self, request, version=None):
        try:
            return Response(
                account.update_profile(
                    request.user,
                    email=request.data.get("email"),
                    language=request.data.get("language"),
                )
            )
        except LoginError as exc:
            return _error(exc)


class PhoneChangeView(ParentView):
    """Смена телефона: {phone} — код на новый номер; {phone, code} — сменить."""

    def post(self, request, version=None):
        try:
            if request.data.get("code"):
                result = account.confirm_phone_change(
                    request.user,
                    request.data.get("phone", ""),
                    request.data["code"],
                    request_meta(request),
                )
            else:
                result = account.request_phone_change(
                    request.user, request.data.get("phone", ""), request_meta(request)
                )
            return Response(result)
        except LoginError as exc:
            return _error(exc)
