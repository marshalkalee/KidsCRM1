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
"""

import enum
import uuid
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from .models import Lesson, LessonEnrollment


class EnrollOutcome(enum.Enum):
    ENROLLED = "enrolled"
    ALREADY_ENROLLED = "already_enrolled"
    CAPACITY_EXCEEDED = "capacity_exceeded"
    LESSON_CANCELLED = "lesson_cancelled"
    LESSON_IN_PAST = "lesson_in_past"


@dataclass
class EnrollResult:
    outcome: EnrollOutcome
    enrollment_id: uuid.UUID | None = None
    capacity: int | None = None
    current_count: int | None = None


_INACTIVE_LESSON_STATUSES = (Lesson.Status.CANCELLED, Lesson.Status.RESCHEDULED)


class LessonService:
    @staticmethod
    @transaction.atomic
    def enroll(lesson_id, child_id, kind, *, actor, confirm_capacity=False) -> EnrollResult:
        lesson = Lesson.objects.select_related("group").get(id=lesson_id)

        if lesson.status in _INACTIVE_LESSON_STATUSES:
            return EnrollResult(EnrollOutcome.LESSON_CANCELLED)
        if lesson.ends_at < timezone.now():
            return EnrollResult(EnrollOutcome.LESSON_IN_PAST)

        if lesson.participants().filter(pk=child_id).exists():
            return EnrollResult(EnrollOutcome.ALREADY_ENROLLED)

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
        )
        AuditLog.record(
            actor=actor,
            action=AuditLog.Action.ENROLL,
            entity=enrollment,
            after={"lesson_id": str(lesson.id), "child_id": str(child_id), "kind": kind},
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
