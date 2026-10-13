"""Teacher substitutions for one or several lessons (TRU-183)."""

import hashlib

from django.db import transaction
from django.utils import timezone

from domains.people.clients.models import ChildContact
from domains.platform.core.active_branch import allowed_branch_ids
from domains.platform.core.audit import AuditLog
from domains.platform.notifications.messaging.service import notify
from domains.platform.users.models import User

from .models import Lesson


class SubstitutionError(ValueError):
    pass


def lesson_branch_id(lesson):
    if lesson.group_id:
        return lesson.group.branch_id
    return lesson.room.branch_id if lesson.room_id else None


def _check_lesson_scope(actor, lessons):
    allowed = allowed_branch_ids(actor)
    if allowed is None:
        return
    if any(lesson_branch_id(lesson) not in allowed for lesson in lessons):
        raise SubstitutionError("Одно или несколько занятий недоступны в ваших филиалах.")


def _check_teacher(organization, teacher, lessons):
    if (
        teacher.organization_id != organization.id
        or teacher.role != User.Role.TEACHER
        or not teacher.is_active
    ):
        raise SubstitutionError("Выберите действующего преподавателя этой организации.")
    allowed = allowed_branch_ids(teacher)
    if allowed is not None and any(lesson_branch_id(lesson) not in allowed for lesson in lessons):
        raise SubstitutionError("Преподаватель не работает в филиале одного из занятий.")


def _notification_rows(organization, lessons):
    """One row per parent, even when several selected lessons concern the family."""
    by_parent = {}
    tz = timezone.zoneinfo.ZoneInfo(organization.timezone or "Asia/Almaty")
    for lesson in lessons:
        child_ids = list(lesson.participants().values_list("id", flat=True))
        links = (
            ChildContact.objects.for_tenant(organization)
            .filter(child_id__in=child_ids)
            .select_related("child", "parent_contact")
        )
        when = timezone.localtime(lesson.starts_at, tz).strftime("%d.%m.%Y %H:%M")
        group = lesson.group.name if lesson.group_id else "Индивидуальное занятие"
        for link in links:
            row = by_parent.setdefault(
                link.parent_contact_id,
                {"parent": link.parent_contact, "children": set(), "lessons": set()},
            )
            row["children"].add(link.child.full_name)
            row["lessons"].add(f"{group}, {when}")
    return by_parent.values()


def _notify_parents(organization, lessons, teacher, actor):
    lesson_key = ",".join(sorted(str(lesson.id) for lesson in lessons))
    digest = hashlib.sha256(f"{lesson_key}:{teacher.id}".encode()).hexdigest()[:24]
    for row in _notification_rows(organization, lessons):
        notify(
            row["parent"],
            "teacher_substitute",
            {
                "child": ", ".join(sorted(row["children"])),
                "teacher": teacher.full_name,
                "lessons": "; ".join(sorted(row["lessons"])),
            },
            dedup_key=f"teacher-substitute:{digest}:{row['parent'].id}",
            user=actor,
        )


@transaction.atomic
def substitute_lessons(*, organization, lesson_ids, teacher, actor, notify_parents=True):
    lessons = list(
        Lesson.objects.select_for_update(of=("self",))
        .filter(organization=organization, id__in=lesson_ids)
        .select_related("group__branch", "room__branch", "teacher", "original_teacher")
        .order_by("starts_at")
    )
    if not lesson_ids or len(lessons) != len(set(lesson_ids)):
        raise SubstitutionError("Одно или несколько занятий не найдены.")
    if any(lesson.status != Lesson.Status.SCHEDULED for lesson in lessons):
        raise SubstitutionError("Замену можно назначить только на запланированные занятия.")
    _check_lesson_scope(actor, lessons)
    _check_teacher(organization, teacher, lessons)

    changed_lessons = []
    for lesson in lessons:
        if lesson.teacher_id == teacher.id:
            continue
        before = {
            "teacher_id": str(lesson.teacher_id) if lesson.teacher_id else None,
            "original_teacher_id": (
                str(lesson.original_teacher_id) if lesson.original_teacher_id else None
            ),
        }
        if lesson.original_teacher_id is None:
            lesson.original_teacher = lesson.teacher
        lesson.teacher = teacher
        lesson.is_modified = True
        lesson.save(update_fields=["teacher", "original_teacher", "is_modified", "updated_at"])
        AuditLog.record(
            actor=actor,
            action=AuditLog.Action.UPDATE,
            entity=lesson,
            before=before,
            after={
                "teacher_id": str(teacher.id),
                "original_teacher_id": (
                    str(lesson.original_teacher_id) if lesson.original_teacher_id else None
                ),
                "teacher_substitution": True,
            },
        )
        changed_lessons.append(lesson)

    if notify_parents and changed_lessons:
        _notify_parents(organization, changed_lessons, teacher, actor)
    return lessons


@transaction.atomic
def remove_substitutions(*, organization, lesson_ids, actor):
    lessons = list(
        Lesson.objects.select_for_update(of=("self",))
        .filter(organization=organization, id__in=lesson_ids)
        .select_related("group__branch", "room__branch", "teacher", "original_teacher")
        .order_by("starts_at")
    )
    if not lesson_ids or len(lessons) != len(set(lesson_ids)):
        raise SubstitutionError("Одно или несколько занятий не найдены.")
    _check_lesson_scope(actor, lessons)
    if any(lesson.original_teacher_id is None for lesson in lessons):
        raise SubstitutionError("На одном или нескольких занятиях замена не назначена.")

    for lesson in lessons:
        before = {
            "teacher_id": str(lesson.teacher_id) if lesson.teacher_id else None,
            "original_teacher_id": str(lesson.original_teacher_id),
        }
        lesson.teacher = lesson.original_teacher
        lesson.original_teacher = None
        lesson.is_modified = True
        lesson.save(update_fields=["teacher", "original_teacher", "is_modified", "updated_at"])
        AuditLog.record(
            actor=actor,
            action=AuditLog.Action.UPDATE,
            entity=lesson,
            before=before,
            after={
                "teacher_id": str(lesson.teacher_id) if lesson.teacher_id else None,
                "original_teacher_id": None,
                "teacher_substitution": False,
            },
        )
    return lessons
