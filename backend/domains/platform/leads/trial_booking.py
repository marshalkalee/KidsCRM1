"""Подбор и запись на пробное занятие из заявки (TRU-100)."""

import datetime

from django.db import transaction
from django.db.models import Count, ExpressionWrapper, F, IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from domains.people.clients.models import Child
from domains.scheduling.groups.models import Group
from domains.scheduling.schedule import holds
from domains.scheduling.schedule.enrollment_service import EnrollOutcome, LessonService
from domains.scheduling.schedule.models import Lesson, LessonEnrollment

from .models import Lead, LeadKind, LeadStatusChange
from .services import LeadTransitionError, change_status


class TrialBookingError(ValueError):
    """Заявку нельзя записать; code позволяет API отличить заполненность."""

    def __init__(self, message, *, code="invalid"):
        super().__init__(message)
        self.code = code


def _validate_lead(lead, *, for_reschedule=False):
    if lead.kind != LeadKind.NEW:
        raise TrialBookingError("Пробное занятие доступно только для новой заявки.")
    missing = []
    if not lead.child_name.strip():
        missing.append("имя ребёнка")
    if lead.child_age is None:
        missing.append("возраст")
    if lead.direction_id is None:
        missing.append("направление")
    if lead.branch_id is None:
        missing.append("филиал")
    if missing:
        raise TrialBookingError(f"Сначала заполните в заявке: {', '.join(missing)}.")
    if for_reschedule and lead.status != Lead.Status.TRIAL_SCHEDULED:
        raise TrialBookingError("Перенести можно только назначенное пробное занятие.")
    if not for_reschedule and not lead.can_move_to(Lead.Status.TRIAL_SCHEDULED):
        raise TrialBookingError(
            f"Из статуса «{lead.get_status_display()}» нельзя записать на пробное."
        )


def trial_lesson_candidates(lead, *, for_reschedule=False):
    """Будущие занятия заявки: направление + возраст + филиал + место."""
    _validate_lead(lead, for_reschedule=for_reschedule)
    age = lead.child_age
    lessons = (
        Lesson.objects.for_tenant(lead.organization)
        .filter(
            status=Lesson.Status.SCHEDULED,
            starts_at__gt=timezone.now(),
            group__isnull=False,
            group__status=Group.Status.ACTIVE,
            group__direction_id=lead.direction_id,
            group__branch_id=lead.branch_id,
        )
        .filter(Q(group__age_min__isnull=True) | Q(group__age_min__lte=age))
        .filter(Q(group__age_max__isnull=True) | Q(group__age_max__gte=age))
        .annotate(
            base_count=Count(
                "group__memberships",
                filter=Q(
                    group__memberships__left_at__isnull=True,
                    group__memberships__deleted_at__isnull=True,
                ),
                distinct=True,
            ),
            overlay_count=Count(
                "enrollments",
                filter=Q(enrollments__cancelled_at__isnull=True),
                distinct=True,
            ),
        )
        .annotate(
            # Чужие брони из каталога (TRU-180) тоже занимают места.
            held_count=Coalesce(
                Subquery(
                    holds.active()
                    .filter(lesson_id=OuterRef("pk"))
                    .exclude(lead_id=lead.id)
                    .values("lesson_id")
                    .annotate(n=Count("id"))
                    .values("n")[:1],
                    output_field=IntegerField(),
                ),
                Value(0),
            ),
        )
        .annotate(
            occupied_count=ExpressionWrapper(
                F("base_count") + F("overlay_count") + F("held_count"),
                output_field=IntegerField(),
            )
        )
        .filter(occupied_count__lt=F("group__capacity"))
        .select_related("group__branch", "group__direction", "room", "teacher")
        .order_by("starts_at")
    )
    if for_reschedule:
        current_lesson_id = (
            lead.trial_enrollments.filter(cancelled_at__isnull=True)
            .values_list("lesson_id", flat=True)
            .first()
        )
        if current_lesson_id is None:
            raise TrialBookingError("Активная запись на пробное не найдена.")
        lessons = lessons.exclude(pk=current_lesson_id)
    return lessons


def _estimated_birth_date(age):
    today = timezone.localdate()
    try:
        return today.replace(year=today.year - age)
    except ValueError:  # 29 февраля в невисокосном году
        return datetime.date(today.year - age, 2, 28)


def _booking_comment(lesson):
    tz = timezone.zoneinfo.ZoneInfo(lesson.organization.timezone or "Asia/Almaty")
    starts = lesson.starts_at.astimezone(tz)
    return (
        f"Пробное занятие: {lesson.group.name}, {starts:%d.%m.%Y %H:%M}, "
        f"{lesson.group.branch.name}."
    )


def _lesson_label(lesson):
    tz = timezone.zoneinfo.ZoneInfo(lesson.organization.timezone or "Asia/Almaty")
    starts = lesson.starts_at.astimezone(tz)
    return f"{lesson.group.name}, {starts:%d.%m.%Y %H:%M}"


def _active_trial_enrollment(lead, *, for_update=False):
    queryset = lead.trial_enrollments.filter(
        cancelled_at__isnull=True,
        kind=LessonEnrollment.Kind.TRIAL,
    ).select_related("child", "lesson__group__branch")
    if for_update:
        queryset = queryset.select_for_update(of=("self",))
    enrollment = queryset.first()
    if enrollment is None:
        raise TrialBookingError("Активная запись на пробное не найдена.")
    return enrollment


def _raise_enrollment_error(result):
    if result.outcome == EnrollOutcome.CAPACITY_EXCEEDED:
        raise TrialBookingError("В занятии больше нет свободных мест.", code="capacity")
    messages = {
        EnrollOutcome.SOURCE_LEAD_ALREADY_BOOKED: "По заявке уже назначено пробное занятие.",
        EnrollOutcome.LESSON_CANCELLED: "Занятие отменено или перенесено.",
        EnrollOutcome.LESSON_IN_PAST: "Занятие уже прошло.",
        EnrollOutcome.ALREADY_ENROLLED: "Ребёнок уже записан на это занятие.",
    }
    raise TrialBookingError(messages.get(result.outcome, "Не удалось записать на пробное."))


@transaction.atomic
def book_trial(lead, lesson_id, *, actor):
    """Создать пробного Child, записать через LessonService, сменить статус."""
    lead = (
        Lead.objects.select_for_update(of=("self",))
        .select_related("branch", "direction", "organization")
        .get(pk=lead.pk)
    )
    _validate_lead(lead)

    if LessonEnrollment.objects.filter(source_lead=lead, cancelled_at__isnull=True).exists():
        raise TrialBookingError("По заявке уже назначено пробное занятие.")

    lesson = trial_lesson_candidates(lead).filter(pk=lesson_id).first()
    if lesson is None:
        raise TrialBookingError(
            "Занятие не подходит по направлению, возрасту или филиалу, либо мест уже нет."
        )

    previous = (
        LessonEnrollment.objects.filter(source_lead=lead)
        .select_related("child")
        .order_by("-created_at")
        .first()
    )
    if previous is not None:
        child = previous.child
    else:
        child = Child.objects.create(
            organization=lead.organization,
            full_name=lead.child_name.strip(),
            birth_date=_estimated_birth_date(lead.child_age),
            birth_date_is_estimated=True,
            gender="",
            status=Child.Status.TRIAL,
        )
        child.directions.add(lead.direction)

    result = LessonService.enroll(
        lesson.id,
        child.id,
        LessonEnrollment.Kind.TRIAL,
        actor=actor,
        source_lead_id=lead.id,
    )
    if result.outcome != EnrollOutcome.ENROLLED:
        _raise_enrollment_error(result)

    try:
        lead = change_status(
            lead,
            to_status=Lead.Status.TRIAL_SCHEDULED,
            actor=actor,
            comment=_booking_comment(lesson),
        )
    except LeadTransitionError as exc:
        raise TrialBookingError(str(exc)) from exc

    enrollment = LessonEnrollment.objects.select_related(
        "lesson__group__branch", "lesson__group__direction", "lesson__room", "lesson__teacher"
    ).get(pk=result.enrollment_id)
    return lead, enrollment


@transaction.atomic
def cancel_trial_booking(lead, *, reason, actor):
    """Отменить конкретную запись, освободить место и вернуть заявку в контакт."""
    reason = reason.strip()
    if not reason:
        raise TrialBookingError("Укажите причину отмены записи.")

    lead = Lead.objects.select_for_update(of=("self",)).get(pk=lead.pk)
    if lead.status != Lead.Status.TRIAL_SCHEDULED:
        raise TrialBookingError("Отменить можно только назначенное пробное занятие.")
    enrollment = _active_trial_enrollment(lead, for_update=True)
    lesson_label = _lesson_label(enrollment.lesson)

    LessonService.cancel_enrollment(enrollment.id, actor=actor, reason=reason)
    try:
        lead = change_status(
            lead,
            to_status=Lead.Status.CONTACTED,
            actor=actor,
            comment=f"Запись на пробное отменена: {lesson_label}. Причина: {reason}",
        )
    except LeadTransitionError as exc:
        raise TrialBookingError(str(exc)) from exc
    return lead, enrollment


@transaction.atomic
def reschedule_trial_booking(lead, lesson_id, *, actor):
    """Атомарно перенести пробного ребёнка на другое подходящее занятие."""
    lead = (
        Lead.objects.select_for_update(of=("self",))
        .select_related("branch", "direction", "organization")
        .get(pk=lead.pk)
    )
    _validate_lead(lead, for_reschedule=True)
    previous = _active_trial_enrollment(lead, for_update=True)
    target = trial_lesson_candidates(lead, for_reschedule=True).filter(pk=lesson_id).first()
    if target is None:
        raise TrialBookingError(
            "Занятие не подходит по направлению, возрасту или филиалу, либо мест уже нет."
        )

    old_label = _lesson_label(previous.lesson)
    new_label = _lesson_label(target)
    LessonService.cancel_enrollment(
        previous.id,
        actor=actor,
        reason=f"Перенос на занятие: {new_label}",
    )
    result = LessonService.enroll(
        target.id,
        previous.child_id,
        LessonEnrollment.Kind.TRIAL,
        actor=actor,
        source_lead_id=lead.id,
    )
    if result.outcome != EnrollOutcome.ENROLLED:
        _raise_enrollment_error(result)

    LeadStatusChange.objects.create(
        organization=lead.organization,
        lead=lead,
        from_status=Lead.Status.TRIAL_SCHEDULED,
        to_status=Lead.Status.TRIAL_SCHEDULED,
        event_type=LeadStatusChange.EventType.TRIAL_RESCHEDULED,
        changed_by=actor,
        comment=f"Пробное занятие перенесено: {old_label} → {new_label}.",
    )
    enrollment = LessonEnrollment.objects.select_related(
        "lesson__group__branch", "lesson__group__direction", "lesson__room", "lesson__teacher"
    ).get(pk=result.enrollment_id)
    return lead, enrollment
