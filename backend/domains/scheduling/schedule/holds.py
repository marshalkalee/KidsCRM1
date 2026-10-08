"""
Бронь места на пробное из каталога (TRU-180, docs/marketplace-readiness.md).

Родитель выбирает занятие в каталоге — появляется заявка с источником
«Маркетплейс» и бронь места на HOLD_HOURS часов. Бронь считается в
свободных местах и каталога, и записи администратором (LessonService.enroll),
поэтому двое не займут последнее место. Центр подтверждает обычной записью
на пробное из карточки заявки; не подтвердил — бронь истекает сама.
"""

import datetime

from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from .models import Lesson, LessonEnrollment, SeatHold

HOLD_HOURS = 24
MARKETPLACE_SOURCE = "Маркетплейс"
_INACTIVE = (Lesson.Status.CANCELLED, Lesson.Status.RESCHEDULED)


class HoldError(Exception):
    """Текст для родителя: почему место не забронировалось."""


def active(now=None):
    """Брони, которые сейчас держат место."""
    from domains.platform.leads.models import Lead

    confirmed = LessonEnrollment.objects.filter(
        lesson_id=OuterRef("lesson_id"),
        source_lead_id=OuterRef("lead_id"),
        cancelled_at__isnull=True,
    )
    return (
        SeatHold.objects.filter(released_at__isnull=True, expires_at__gt=now or timezone.now())
        .exclude(lead__status=Lead.Status.REJECTED)
        .exclude(Exists(confirmed))
    )


def held_count(lesson, *, exclude_lead_id=None) -> int:
    holds = active().filter(lesson=lesson)
    if exclude_lead_id is not None:
        holds = holds.exclude(lead_id=exclude_lead_id)
    return holds.count()


@transaction.atomic
def hold_seat(
    *, organization, lesson_id, parent_name, phone, child_name="", child_age=None, hours=HOLD_HOURS
) -> SeatHold:
    """Заявка из каталога + бронь места. Блокировка занятия — та же, что в
    LessonService.enroll: последнее место достаётся одному."""
    from domains.platform.leads.models import Lead, LeadSource
    from domains.platform.leads.services import create_lead

    lesson = (
        Lesson.objects.for_tenant(organization)
        .select_for_update(of=("self",))
        .select_related("group")
        .filter(id=lesson_id, group__isnull=False, group__is_public=True, deleted_at__isnull=True)
        .first()
    )
    now = timezone.now()
    if lesson is None:
        raise HoldError("Занятие не найдено.")
    if lesson.status in _INACTIVE or lesson.starts_at <= now:
        raise HoldError("На это занятие уже нельзя записаться.")
    group = lesson.group
    if not group.trial_available:
        raise HoldError("В этой группе нет пробных занятий.")
    if lesson.participants().count() + held_count(lesson) >= group.capacity:
        raise HoldError("Свободных мест на это занятие нет.")

    source, _ = LeadSource.objects.get_or_create(
        organization=organization, name=MARKETPLACE_SOURCE, defaults={"is_active": True}
    )
    lead = create_lead(
        organization=organization,
        actor=None,
        kind=Lead.Kind.NEW,
        branch_id=group.branch_id,
        direction_id=group.direction_id,
        source=source,
        parent_name=parent_name.strip(),
        phone=phone,
        child_name=child_name.strip(),
        child_age=child_age,
    )
    return SeatHold.objects.create(
        organization=organization,
        lesson=lesson,
        lead=lead,
        expires_at=now + datetime.timedelta(hours=hours),
    )
