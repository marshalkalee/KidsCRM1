"""Staff-side processing of parent lesson requests (TRU-146)."""

from django.db import transaction
from django.utils import timezone

from domains.platform.core.audit import AuditLog
from domains.platform.tasks.models import Task
from domains.scheduling.attendance.models import Attendance
from domains.scheduling.schedule.enrollment_service import EnrollOutcome, LessonService
from domains.scheduling.schedule.models import Lesson, LessonEnrollment

from .models import ParentLessonRequest


class RequestProcessingError(Exception):
    def __init__(self, message, *, status_code=409):
        super().__init__(message)
        self.status_code = status_code


ENROLL_ERRORS = {
    EnrollOutcome.CAPACITY_EXCEEDED: (
        "Свободных мест уже нет. Запрос можно отклонить с объяснением."
    ),
    EnrollOutcome.LESSON_CANCELLED: "Занятие отменено или перенесено.",
    EnrollOutcome.LESSON_IN_PAST: "Занятие уже прошло — записать ребёнка нельзя.",
    EnrollOutcome.SOURCE_CHILD_MISMATCH: "Пропуск для отработки принадлежит другому ребёнку.",
    EnrollOutcome.SOURCE_ALREADY_USED: "Этот пропуск уже использован для другой отработки.",
    EnrollOutcome.SOURCE_EXPIRED: "Срок отработки уже истёк.",
    EnrollOutcome.SOURCE_LIMIT_EXCEEDED: "Лимит отработок по абонементу уже исчерпан.",
    EnrollOutcome.SOURCE_DIRECTION_MISMATCH: "Занятие больше не подходит для этой отработки.",
}


def _close_task(parent_request, actor, comment):
    Task.objects.for_tenant(parent_request.organization).filter(
        type=Task.Type.PARENT_REQUEST,
        source_key=f"parent-request:{parent_request.id}",
        status=Task.Status.OPEN,
    ).update(
        status=Task.Status.DONE,
        closing_comment=comment,
        updated_at=timezone.now(),
    )


def _finish(parent_request, actor, status_value, *, rejection_reason=""):
    before = {"status": parent_request.status}
    parent_request.status = status_value
    parent_request.processed_by = actor
    parent_request.processed_at = timezone.now()
    parent_request.rejection_reason = rejection_reason.strip()
    parent_request.save(
        update_fields=[
            "status",
            "processed_by",
            "processed_at",
            "rejection_reason",
            "updated_at",
        ]
    )
    _close_task(
        parent_request,
        actor,
        "Одобрено" if status_value == ParentLessonRequest.Status.APPROVED else rejection_reason,
    )
    AuditLog.record(
        actor=actor,
        action=AuditLog.Action.UPDATE,
        entity=parent_request,
        before=before,
        after={"status": status_value, "rejection_reason": rejection_reason},
    )
    return parent_request


@transaction.atomic
def approve_parent_request(request_id, *, actor):
    parent_request = (
        ParentLessonRequest.objects.for_tenant(actor.organization)
        .select_for_update(of=("self",))
        .select_related("lesson", "child", "source_attendance")
        .get(pk=request_id)
    )
    if parent_request.status != ParentLessonRequest.Status.NEW:
        raise RequestProcessingError("Этот запрос уже обработан.")

    lesson = parent_request.lesson
    if lesson.status != Lesson.Status.SCHEDULED:
        raise RequestProcessingError(
            "Занятие отменено или перенесено. Отклоните запрос с пояснением."
        )

    if parent_request.type == ParentLessonRequest.Type.ENROLL:
        kind = (
            LessonEnrollment.Kind.MAKEUP
            if parent_request.kind == ParentLessonRequest.Kind.MAKEUP
            else LessonEnrollment.Kind.REGULAR
        )
        result = LessonService.enroll(
            lesson.id,
            parent_request.child_id,
            kind,
            actor=actor,
            source_attendance_id=parent_request.source_attendance_id,
        )
        if result.outcome not in (EnrollOutcome.ENROLLED, EnrollOutcome.ALREADY_ENROLLED):
            raise RequestProcessingError(
                ENROLL_ERRORS.get(result.outcome, "Запрос сейчас нельзя одобрить.")
            )
    else:
        reason = {
            ParentLessonRequest.CancelReason.ILLNESS: Attendance.AbsenceReason.ILLNESS,
            ParentLessonRequest.CancelReason.FAMILY: Attendance.AbsenceReason.FAMILY,
        }.get(parent_request.cancel_reason, Attendance.AbsenceReason.NO_REASON)
        attendance, _ = Attendance.objects.get_or_create(
            organization=parent_request.organization,
            lesson=lesson,
            child=parent_request.child,
            defaults={"status": Attendance.Status.ABSENT},
        )
        attendance.mark(Attendance.Status.ABSENT, actor=actor, absence_reason=reason)

    return _finish(parent_request, actor, ParentLessonRequest.Status.APPROVED)


@transaction.atomic
def reject_parent_request(request_id, *, actor, reason):
    reason = (reason or "").strip()
    if not reason:
        raise RequestProcessingError("Укажите причину отказа.", status_code=400)
    parent_request = (
        ParentLessonRequest.objects.for_tenant(actor.organization)
        .select_for_update(of=("self",))
        .get(pk=request_id)
    )
    if parent_request.status != ParentLessonRequest.Status.NEW:
        raise RequestProcessingError("Этот запрос уже обработан.")
    return _finish(
        parent_request,
        actor,
        ParentLessonRequest.Status.REJECTED,
        rejection_reason=reason[:1000],
    )
