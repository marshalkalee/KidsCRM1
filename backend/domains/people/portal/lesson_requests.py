"""Parent lesson requests: validation and task creation for TRU-143."""

import datetime

from django.db import IntegrityError, transaction
from django.utils import timezone

from domains.people.clients.models import Child
from domains.platform.tasks.models import Task
from domains.platform.tenants.org_settings import (
    PARENT_CANCEL_CHARGE_ON_TIME,
    PARENT_CANCEL_NOTICE_HOURS,
    get_org_setting,
)
from domains.platform.users.models import User
from domains.scheduling.schedule.enrollment_service import (
    available_makeups_for_child,
    makeup_candidate_lessons,
    makeup_policy_for_attendance,
)
from domains.scheduling.schedule.models import Lesson

from .models import ParentLessonRequest


class ParentRequestError(Exception):
    def __init__(self, message, *, status_code=400):
        super().__init__(message)
        self.status_code = status_code


def _age_on(child, day):
    born = child.birth_date
    return day.year - born.year - ((day.month, day.day) < (born.month, born.day))


def _spots_left(lesson):
    if not lesson.group_id:
        return 0
    return max(lesson.group.capacity - lesson.participants().count(), 0)


def regular_candidate_lessons(child):
    """Future lessons matching the child's current direction and age."""
    direction_ids = child.group_memberships.filter(
        deleted_at__isnull=True, left_at__isnull=True
    ).values_list("group__direction_id", flat=True)
    lessons = (
        Lesson.objects.for_tenant(child.organization)
        .filter(
            group__isnull=False,
            group__direction_id__in=direction_ids,
            group__status="active",
            status=Lesson.Status.SCHEDULED,
            starts_at__gt=timezone.now(),
        )
        .select_related("group__direction", "group__branch", "room", "teacher")
        .order_by("starts_at")
    )
    result = []
    for lesson in lessons:
        if lesson.participants().filter(pk=child.id).exists():
            continue
        local_day = timezone.localtime(lesson.starts_at).date()
        age = _age_on(child, local_day)
        if lesson.group.age_min is not None and age < lesson.group.age_min:
            continue
        if lesson.group.age_max is not None and age > lesson.group.age_max:
            continue
        if _spots_left(lesson) > 0:
            result.append(lesson)
    return result


def makeup_source(child, attendance_id):
    for row in available_makeups_for_child(child.organization, child.id):
        if row["attendance"].id == attendance_id:
            return row
    return None


def makeup_candidates(child, source_attendance):
    return [
        lesson
        for lesson in makeup_candidate_lessons(source_attendance, child.organization)
        if not lesson.participants().filter(pk=child.id).exists() and _spots_left(lesson) > 0
    ]


def _assignee(organization):
    return (
        User.objects.filter(
            organization=organization,
            is_active=True,
            role__in=[User.Role.ADMIN, User.Role.MANAGER, User.Role.OWNER],
        )
        .order_by("role", "full_name")
        .first()
    )


def task_text(parent_request) -> tuple[str, str]:
    """Заголовок и описание задачи по запросу родителя — человеческим языком:
    группа, филиал, время по часовому поясу центра, причина и комментарий
    родителя. Без служебных идентификаторов и строк моделей."""
    lesson = parent_request.lesson
    branch = lesson.group.branch if lesson.group_id else getattr(lesson.room, "branch", None)
    tz = timezone.zoneinfo.ZoneInfo(parent_request.organization.timezone or "Asia/Almaty")
    start = timezone.localtime(lesson.starts_at, tz)
    if parent_request.type == ParentLessonRequest.Type.ENROLL:
        title = (
            "Запись на отработку"
            if parent_request.kind == ParentLessonRequest.Kind.MAKEUP
            else "Запись на занятие"
        )
    else:
        title = "Отмена занятия"
    group_name = lesson.group.name if lesson.group_id else ""
    place = ", ".join(part for part in (group_name, branch.name if branch else "") if part)
    when = f"{start:%d.%m} в {start:%H:%M}"
    lines = [f"{place} — {when}" if place else when]
    if parent_request.type == ParentLessonRequest.Type.CANCEL:
        lines.append(f"Причина: {parent_request.get_cancel_reason_display().lower()}.")
        lines.append(
            "Предупредили вовремя — занятие не спишется."
            if not parent_request.will_be_charged
            else (
                "Предупредили позже срока — занятие спишется."
                if not parent_request.notice_is_timely
                else "Занятие спишется по правилам центра."
            )
        )
    if parent_request.comment:
        lines.append(f"Комментарий родителя: «{parent_request.comment.strip()}»")
    return title, "\n".join(lines)


def _create_task(parent_request):
    lesson = parent_request.lesson
    branch = lesson.group.branch if lesson.group_id else getattr(lesson.room, "branch", None)
    title, description = task_text(parent_request)
    Task.objects.get_or_create(
        organization=parent_request.organization,
        type=Task.Type.PARENT_REQUEST,
        source_key=f"parent-request:{parent_request.id}",
        defaults={
            "assigned_to": _assignee(parent_request.organization),
            "child": parent_request.child,
            "branch": branch,
            "source": Task.Source.AUTO,
            "due_at": timezone.now() + datetime.timedelta(hours=4),
            "title": title,
            "description": description,
        },
    )


@transaction.atomic
def create_parent_request(
    *,
    account,
    child,
    lesson_id,
    request_type,
    comment="",
    source_attendance_id=None,
    cancel_reason="",
):
    # Serialise requests for one child so two simultaneous requests cannot
    # both pass an optional subscription makeup limit.
    Child.objects.select_for_update().get(pk=child.pk)
    lesson = (
        Lesson.objects.for_tenant(child.organization)
        .select_for_update(of=("self",))
        .select_related("group__direction", "group__branch", "room", "teacher")
        .filter(id=lesson_id)
        .first()
    )
    if lesson is None:
        raise ParentRequestError("Занятие не найдено.", status_code=404)
    if lesson.status != Lesson.Status.SCHEDULED or lesson.starts_at <= timezone.now():
        raise ParentRequestError("На это занятие уже нельзя отправить запрос.")

    kind = ParentLessonRequest.Kind.REGULAR
    source_attendance = None
    if source_attendance_id:
        if request_type != ParentLessonRequest.Type.ENROLL:
            raise ParentRequestError("Отработка доступна только для запроса на запись.")
        source = makeup_source(child, source_attendance_id)
        if source is None:
            raise ParentRequestError(
                "Срок отработки истёк или пропуск уже использован.", status_code=409
            )
        source_attendance = source["attendance"]
        policy = makeup_policy_for_attendance(source_attendance)
        if policy["limit"] is not None and policy["subscription"] is not None:
            pending = (
                ParentLessonRequest.objects.for_tenant(child.organization)
                .filter(
                    child=child,
                    kind=ParentLessonRequest.Kind.MAKEUP,
                    status=ParentLessonRequest.Status.NEW,
                    source_attendance__lesson__starts_at__date__gte=policy[
                        "subscription"
                    ].starts_on,
                    source_attendance__lesson__starts_at__date__lte=policy["subscription"].ends_on,
                )
                .count()
            )
            if source["makeups_used"] + pending >= policy["limit"]:
                raise ParentRequestError(
                    "Лимит отработок по абонементу уже использован.", status_code=409
                )
        if lesson.id not in {row.id for row in makeup_candidates(child, source_attendance)}:
            raise ParentRequestError("Это занятие не подходит для выбранной отработки.")
        kind = ParentLessonRequest.Kind.MAKEUP
    elif request_type == ParentLessonRequest.Type.ENROLL:
        if lesson.id not in {row.id for row in regular_candidate_lessons(child)}:
            raise ParentRequestError("Это занятие не подходит ребёнку или свободных мест уже нет.")
    elif request_type == ParentLessonRequest.Type.CANCEL:
        if not lesson.participants().filter(pk=child.id).exists():
            raise ParentRequestError("Ребёнок не записан на это занятие.")
        if cancel_reason not in ParentLessonRequest.CancelReason.values:
            raise ParentRequestError("Укажите причину отмены занятия.")
    else:
        raise ParentRequestError("Неизвестный тип запроса.")

    notice_hours_required = None
    notice_is_timely = None
    will_be_charged = None
    if request_type == ParentLessonRequest.Type.CANCEL:
        notice_hours_required = int(get_org_setting(child.organization, PARENT_CANCEL_NOTICE_HOURS))
        notice_deadline = lesson.starts_at - datetime.timedelta(hours=notice_hours_required)
        notice_is_timely = timezone.now() <= notice_deadline
        charge_on_time = bool(get_org_setting(child.organization, PARENT_CANCEL_CHARGE_ON_TIME))
        will_be_charged = not notice_is_timely or charge_on_time

    try:
        parent_request = ParentLessonRequest.objects.create(
            organization=child.organization,
            requested_by=account,
            child=child,
            lesson=lesson,
            type=request_type,
            kind=kind,
            comment=comment.strip(),
            cancel_reason=(
                cancel_reason if request_type == ParentLessonRequest.Type.CANCEL else ""
            ),
            notice_hours_required=notice_hours_required,
            notice_is_timely=notice_is_timely,
            will_be_charged=will_be_charged,
            source_attendance=source_attendance,
            spots_available_at_request=(
                _spots_left(lesson) if request_type == ParentLessonRequest.Type.ENROLL else None
            ),
        )
    except IntegrityError as exc:
        raise ParentRequestError(
            "Такой запрос уже ожидает решения администратора.", status_code=409
        ) from exc
    _create_task(parent_request)
    return parent_request
