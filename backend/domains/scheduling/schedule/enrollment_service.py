"""
LessonService — контракт №3 из TRU-8 (см. backend/docs/contracts.md):
запись ребёнка на занятие «поверх» состава группы, один механизм для
отработок (M1) и пробных занятий (M2), чтобы список участников занятия не
собирался по-разному в разных местах (посещаемость, вместимость, отмена).

Контроль вместимости — предупреждение с подтверждением, не жёсткий запрет
(та же философия, что у конфликтов по залу/преподавателю, TRU-46:
administrator видит проблему и решает сам, а не упирается в стену).

Правило списания по типу (M1, до согласования с Bekzat — см. TRU-53):
отработка уже оплачена пропущенным занятием, пробное — бесплатно, обе не
списывают новый сеанс с абонемента. Применяется в Attendance._consume()
(schedule -> attendance тем же путём, что и schedule -> money).

TRU-54 (отработки) — правила Discovery №1 уточнены с пользователем (не с
самим True Ballet — ответы зафиксированы как временное M1-решение до
подтверждения клиентом):
* пропуск сгорает через MAKEUP_EXPIRY_DAYS дней после даты пропущенного
  занятия;
* отрабатывать можно только в том же направлении, где пропустили;
* лимита отработок в месяц на M1 нет.
"""

import datetime
import enum
import uuid
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from .models import Lesson, LessonEnrollment

# TRU-54, Discovery №1 (M1-дефолт, не подтверждено True Ballet напрямую).
MAKEUP_EXPIRY_DAYS = 14


class EnrollOutcome(enum.Enum):
    ENROLLED = "enrolled"
    ALREADY_ENROLLED = "already_enrolled"
    CAPACITY_EXCEEDED = "capacity_exceeded"
    LESSON_CANCELLED = "lesson_cancelled"
    LESSON_IN_PAST = "lesson_in_past"
    SOURCE_CHILD_MISMATCH = "source_child_mismatch"
    SOURCE_ALREADY_USED = "source_already_used"
    SOURCE_EXPIRED = "source_expired"
    SOURCE_DIRECTION_MISMATCH = "source_direction_mismatch"


@dataclass
class EnrollResult:
    outcome: EnrollOutcome
    enrollment_id: uuid.UUID | None = None
    capacity: int | None = None
    current_count: int | None = None


_INACTIVE_LESSON_STATUSES = (Lesson.Status.CANCELLED, Lesson.Status.RESCHEDULED)


def _org_today(organization):
    tz = timezone.zoneinfo.ZoneInfo(organization.timezone or "Asia/Almaty")
    return timezone.now().astimezone(tz).date()


def _direction_id(lesson):
    return lesson.group.direction_id if lesson.group_id else None


class LessonService:
    @staticmethod
    @transaction.atomic
    def enroll(
        lesson_id, child_id, kind, *, actor, confirm_capacity=False, source_attendance_id=None
    ) -> EnrollResult:
        lesson = Lesson.objects.select_related("group").get(id=lesson_id)

        if lesson.status in _INACTIVE_LESSON_STATUSES:
            return EnrollResult(EnrollOutcome.LESSON_CANCELLED)
        if lesson.ends_at < timezone.now():
            return EnrollResult(EnrollOutcome.LESSON_IN_PAST)

        if lesson.participants().filter(pk=child_id).exists():
            return EnrollResult(EnrollOutcome.ALREADY_ENROLLED)

        source_attendance = None
        if source_attendance_id is not None:
            from domains.scheduling.attendance.models import Attendance

            source_attendance = Attendance.objects.select_related("lesson", "lesson__group").get(
                id=source_attendance_id
            )

            if source_attendance.child_id != child_id:
                return EnrollResult(EnrollOutcome.SOURCE_CHILD_MISMATCH)
            if LessonEnrollment.objects.filter(
                source_attendance=source_attendance, cancelled_at__isnull=True
            ).exists():
                return EnrollResult(EnrollOutcome.SOURCE_ALREADY_USED)
            expires_on = source_attendance.lesson.starts_at.astimezone(
                timezone.zoneinfo.ZoneInfo(lesson.organization.timezone or "Asia/Almaty")
            ).date() + datetime.timedelta(days=MAKEUP_EXPIRY_DAYS)
            if expires_on < _org_today(lesson.organization):
                return EnrollResult(EnrollOutcome.SOURCE_EXPIRED)
            if (
                _direction_id(source_attendance.lesson) != _direction_id(lesson)
                or _direction_id(lesson) is None
            ):
                return EnrollResult(EnrollOutcome.SOURCE_DIRECTION_MISMATCH)

        capacity = lesson.group.capacity if lesson.group_id else None
        current_count = lesson.participants().count()
        if capacity is not None and current_count + 1 > capacity and not confirm_capacity:
            return EnrollResult(
                EnrollOutcome.CAPACITY_EXCEEDED, capacity=capacity, current_count=current_count
            )

        from domains.platform.core.audit import AuditLog

        enrollment = LessonEnrollment.objects.create(
            organization=lesson.organization,
            lesson=lesson,
            child_id=child_id,
            kind=kind,
            enrolled_by=actor,
            source_attendance=source_attendance,
        )
        AuditLog.record(
            actor=actor,
            action=AuditLog.Action.ENROLL,
            entity=enrollment,
            after={
                "lesson_id": str(lesson.id),
                "child_id": str(child_id),
                "kind": kind,
                "source_attendance_id": str(source_attendance_id) if source_attendance_id else None,
            },
        )
        return EnrollResult(EnrollOutcome.ENROLLED, enrollment_id=enrollment.id)

    @staticmethod
    @transaction.atomic
    def cancel_enrollment(enrollment_id, *, actor) -> bool:
        """True — реально отменили; False — уже была отменена (идемпотентно)."""
        from domains.platform.core.audit import AuditLog

        enrollment = LessonEnrollment.objects.select_for_update().get(id=enrollment_id)
        if enrollment.cancelled_at is not None:
            return False

        before = {"cancelled_at": None}
        enrollment.cancelled_at = timezone.now()
        enrollment.save(update_fields=["cancelled_at", "updated_at"])
        AuditLog.record(
            actor=actor,
            action=AuditLog.Action.UNENROLL,
            entity=enrollment,
            before=before,
            after={"cancelled_at": enrollment.cancelled_at.isoformat()},
        )
        return True


def available_makeups_for_child(organization, child_id):
    """TRU-54: пропуски ребёнка, ещё доступные для отработки — не
    использованы (нет активной записи с этим source_attendance) и не
    сгорели (в пределах MAKEUP_EXPIRY_DAYS от даты пропущенного занятия).
    Возвращает список словарей (не queryset — expires_on/days_left
    считаются здесь, не хранятся)."""
    from domains.scheduling.attendance.models import Attendance

    tz = timezone.zoneinfo.ZoneInfo(organization.timezone or "Asia/Almaty")
    today = _org_today(organization)

    used_attendance_ids = LessonEnrollment.objects.filter(
        source_attendance__isnull=False, cancelled_at__isnull=True
    ).values_list("source_attendance_id", flat=True)

    qs = (
        Attendance.objects.for_tenant(organization)
        .filter(child_id=child_id, status=Attendance.Status.ABSENT)
        .exclude(id__in=used_attendance_ids)
        .select_related("lesson", "lesson__group", "lesson__room")
        .order_by("-lesson__starts_at")
    )

    results = []
    for attendance in qs:
        expires_on = attendance.lesson.starts_at.astimezone(tz).date() + datetime.timedelta(
            days=MAKEUP_EXPIRY_DAYS
        )
        if expires_on < today:
            continue
        results.append(
            {
                "attendance": attendance,
                "expires_on": expires_on,
                "days_left": (expires_on - today).days,
            }
        )
    return results


def makeup_candidate_lessons(source_attendance, organization):
    """TRU-54: занятия, подходящие для отработки конкретного пропуска —
    то же направление (Discovery №1: кросс-направление не разрешено),
    ещё не наступившие, статус «запланировано». Вместимость НЕ
    фильтруется здесь (только считается — capacity/current_count в
    сериализаторе), чтобы не прятать вариант, если администратор всё
    равно захочет записать «поверх» с подтверждением (тот же принцип,
    что при создании самой записи, см. LessonService.enroll)."""
    source_lesson = source_attendance.lesson
    if not source_lesson.group_id:
        return Lesson.objects.none()

    return (
        Lesson.objects.for_tenant(organization)
        .filter(
            group__direction_id=source_lesson.group.direction_id,
            status=Lesson.Status.SCHEDULED,
            starts_at__gt=timezone.now(),
        )
        .exclude(id=source_lesson.id)
        .select_related("group", "room", "teacher")
        .order_by("starts_at")
    )
