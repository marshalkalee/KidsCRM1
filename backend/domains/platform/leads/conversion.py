"""Конвертация заявки после пробного занятия (TRU-102).

Поиск совпадений всегда выполняет ChildService. Этот модуль только
оркестрирует явное решение администратора и переносит историю с временного
trial-ребёнка, созданного при записи на занятие, на итоговую карточку.
"""

from django.db import transaction

from domains.people.clients.models import Child
from domains.people.clients.services import ChildService, DuplicateReason
from domains.platform.core.audit import AuditLog
from domains.scheduling.attendance.models import Attendance
from domains.scheduling.schedule.models import LessonEnrollment

from .models import Lead


class LeadConversionError(ValueError):
    pass


def _trial_candidate(lead):
    enrollment = (
        LessonEnrollment.objects.for_tenant(lead.organization)
        .filter(source_lead=lead, cancelled_at__isnull=True)
        .select_related("child")
        .first()
    )
    return enrollment.child if enrollment else None


def _serialize_match(match):
    child = match.child
    parent = match.parent
    return {
        "reason": match.reason,
        "child": child
        and {
            "id": str(child.id),
            "full_name": child.full_name,
            "birth_date": child.birth_date.isoformat(),
            "age": child.age,
            "gender": child.gender,
            "status": child.status,
            "consent_given": child.consent_given,
        },
        "parent": parent
        and {
            "id": str(parent.id),
            "full_name": parent.full_name,
            "phones": list(parent.phones.values_list("number", flat=True)),
        },
    }


def conversion_preview(lead, *, child_name=None, birth_date=None):
    """Данные формы и совпадения без каких-либо изменений в базе."""
    candidate = _trial_candidate(lead)
    effective_name = child_name or lead.child_name or (candidate and candidate.full_name) or ""
    # Приблизительную дату из возраста нельзя выдавать за точную и нельзя
    # использовать как сильный критерий дубля.
    default_birth_date = (
        candidate.birth_date
        if candidate is not None and not candidate.birth_date_is_estimated
        else None
    )
    effective_birth_date = birth_date or default_birth_date
    matches = ChildService.find_duplicates(
        lead.organization,
        phone=lead.phone,
        child_name=effective_name or None,
        birth_date=effective_birth_date,
    )
    # Временный trial-ребёнок создан самой этой заявкой. Это не дубль, а
    # источник истории для будущей итоговой карточки.
    if candidate is not None:
        matches = [item for item in matches if item.child is None or item.child.id != candidate.id]
    return {
        "converted": bool(lead.converted_child_id),
        "converted_child_id": str(lead.converted_child_id) if lead.converted_child_id else None,
        "allowed": lead.kind == Lead.Kind.NEW
        and (
            lead.status == Lead.Status.TRIAL_ATTENDED
            or lead.status == Lead.Status.PURCHASED
            or lead.can_move_to(Lead.Status.PURCHASED)
        ),
        "defaults": {
            "child_name": effective_name,
            "birth_date": default_birth_date.isoformat() if default_birth_date else "",
            "gender": candidate.gender if candidate else "",
            "parent_name": lead.parent_name,
            "phone": lead.phone,
            "direction_id": str(lead.direction_id) if lead.direction_id else None,
            "direction_name": lead.direction.name if lead.direction_id else None,
            "branch_id": str(lead.branch_id) if lead.branch_id else None,
            "branch_name": lead.branch.name if lead.branch_id else None,
        },
        "matches": [_serialize_match(match) for match in matches],
    }


def _matched_selection(matches, *, decision, child_id=None, parent_id=None):
    if decision == "existing_child":
        match = next(
            (item for item in matches if item.child and str(item.child.id) == str(child_id)),
            None,
        )
        if match is None:
            raise LeadConversionError("Выбранный ребёнок не найден среди совпадений.")
        return match
    if decision == "existing_parent":
        match = next(
            (
                item
                for item in matches
                if item.reason == DuplicateReason.EXISTING_PARENT_NEW_CHILD
                and item.parent
                and str(item.parent.id) == str(parent_id)
            ),
            None,
        )
        if match is None:
            raise LeadConversionError("Выбранный родитель не найден среди совпадений.")
        return match
    return None


def _move_trial_history(organization, candidate, target):
    if candidate is None or candidate.pk == target.pk:
        return

    enrollments = list(LessonEnrollment.objects.for_tenant(organization).filter(child=candidate))
    for enrollment in enrollments:
        conflict = LessonEnrollment.objects.for_tenant(organization).filter(
            lesson=enrollment.lesson,
            child=target,
            cancelled_at__isnull=True,
        )
        if enrollment.cancelled_at is None and conflict.exists():
            raise LeadConversionError(
                "У выбранного ребёнка уже есть отдельная запись на это пробное занятие."
            )

    attendances = list(Attendance.objects.for_tenant(organization).filter(child=candidate))
    for attendance in attendances:
        if (
            Attendance.objects.for_tenant(organization)
            .filter(lesson=attendance.lesson, child=target)
            .exists()
        ):
            raise LeadConversionError("У выбранного ребёнка уже есть отметка на этом занятии.")

    for enrollment in enrollments:
        enrollment.child = target
        enrollment.save(update_fields=["child", "updated_at"])
    for attendance in attendances:
        attendance.child = target
        attendance.save(update_fields=["child", "updated_at"])
    candidate.delete()


@transaction.atomic
def convert_lead(lead, *, actor, data):
    """Подтвердить выбранный администратором вариант конвертации."""
    lead = Lead.objects.select_for_update().get(pk=lead.pk, organization=lead.organization)
    if lead.converted_child_id:
        return lead, False
    if lead.kind != Lead.Kind.NEW or not (
        lead.status == Lead.Status.TRIAL_ATTENDED
        or lead.status == Lead.Status.PURCHASED
        or lead.can_move_to(Lead.Status.PURCHASED)
    ):
        raise LeadConversionError("Из текущего статуса нельзя оформить клиента.")

    matches = ChildService.find_duplicates(
        lead.organization,
        phone=lead.phone,
        child_name=data["child_name"],
        birth_date=data["birth_date"],
    )
    candidate = _trial_candidate(lead)
    if candidate is not None:
        matches = [item for item in matches if item.child is None or item.child.id != candidate.id]
    selected = _matched_selection(
        matches,
        decision=data["decision"],
        child_id=data.get("child_id"),
        parent_id=data.get("parent_id"),
    )
    if data["decision"] == "existing_child":
        target = Child.objects.for_tenant(lead.organization).get(pk=selected.child.pk)
        parent_data = (
            {"id": str(selected.parent.id)}
            if selected.parent
            else {"full_name": data["parent_name"], "phones": [lead.phone]}
        )
        ChildService.link_parent(
            lead.organization,
            target,
            parent_data=parent_data,
            link_role=data["link_role"],
        )
        # Галочка в форме подтверждает получение согласия сейчас; точные
        # ФИО/дата существующей карточки не перезаписываются данными заявки.
        target.consent_given = True
        if target.status == Child.Status.TRIAL:
            target.status = Child.Status.ACTIVE
        target.save(update_fields=["consent_given", "status", "updated_at"])
    else:
        parent_data = (
            {"id": str(selected.parent.id)}
            if data["decision"] == "existing_parent"
            else {"full_name": data["parent_name"], "phones": [lead.phone]}
        )
        target = ChildService.create_with_parent(
            lead.organization,
            child_data={
                "full_name": data["child_name"],
                "birth_date": data["birth_date"],
                "birth_date_is_estimated": False,
                "gender": data["gender"],
                "status": Child.Status.ACTIVE,
                "consent_given": True,
            },
            parent_data=parent_data,
            link_role=data["link_role"],
        )

    if lead.direction_id:
        target.directions.add(lead.direction_id)
    _move_trial_history(lead.organization, candidate, target)

    lead.converted_child = target
    lead.save(update_fields=["converted_child", "updated_at"])
    AuditLog.record(
        actor=actor,
        action=AuditLog.Action.UPDATE,
        entity=lead,
        before={"converted_child": None},
        after={"converted_child": str(target.id), "conversion_decision": data["decision"]},
    )
    return lead, True
