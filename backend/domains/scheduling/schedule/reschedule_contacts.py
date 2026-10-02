"""
Список «кого обзвонить» после переноса занятия (TRU-49, ТЗ п. 4.2, п. 4.5).

MVP не отправляет ничего сама — готовит администратору рабочий список:
контакт, готовый текст, ссылка wa.me с уже подставленным сообщением, и
кто уже обзвонён (RescheduleCallLog — сохраняется, не теряется при уходе
с экрана).
"""

from urllib.parse import quote

from django.utils import timezone

from domains.people.clients.models import ChildContact

from .models import Lesson, LessonEnrollment, RescheduleCallLog

RU_MONTHS_GENITIVE = [
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]


def _format_ru_datetime(dt_utc, tz):
    local = dt_utc.astimezone(tz)
    return f"{local.day} {RU_MONTHS_GENITIVE[local.month - 1]} в {local.strftime('%H:%M')}"


def build_reschedule_message(old_lesson, new_lesson, tz):
    old_label = _format_ru_datetime(old_lesson.starts_at, tz)
    new_label = _format_ru_datetime(new_lesson.starts_at, tz)
    return f"Занятие {old_label} переносится на {new_label}."


def build_cancellation_message(lesson, tz):
    lesson_label = _format_ru_datetime(lesson.starts_at, tz)
    reason = lesson.cancel_reason.strip()
    suffix = f" Причина: {reason}." if reason else ""
    return f"Занятие {lesson_label} отменено центром.{suffix}"


def build_lesson_change_message(lesson, tz):
    if lesson.status == Lesson.Status.CANCELLED:
        return build_cancellation_message(lesson, tz)
    return build_reschedule_message(lesson, lesson.rescheduled_to, tz)


def _whatsapp_link(number, message):
    if not number:
        return None
    digits = "".join(ch for ch in number if ch.isdigit())
    if not digits:
        return None
    return f"https://wa.me/{digits}?text={quote(message)}"


def build_who_to_call(lesson, organization):
    """lesson — исходное (перенесённое) занятие, lesson.rescheduled_to —
    новое. Возвращает {message, contacts: [...]}. Группирует по контакту
    (parent_contact), а не по ребёнку — один родитель с двумя детьми в
    одной группе получает одну карточку на обзвон, не две."""
    tz = timezone.zoneinfo.ZoneInfo(organization.timezone or "Asia/Almaty")
    message = build_lesson_change_message(lesson, tz)

    children = list(lesson.participants())
    child_by_id = {child.id: child for child in children}
    trial_enrollments = list(
        LessonEnrollment.objects.filter(
            lesson=lesson,
            kind=LessonEnrollment.Kind.TRIAL,
            cancelled_at__isnull=True,
            source_lead__isnull=False,
        )
        .select_related("source_lead", "child")
        .order_by("created_at")
    )
    trial_child_ids = {enrollment.child_id for enrollment in trial_enrollments}

    child_contacts = (
        ChildContact.objects.for_tenant(organization)
        .filter(child_id__in=child_by_id.keys())
        .exclude(child_id__in=trial_child_ids)
        .select_related("parent_contact")
        .prefetch_related("parent_contact__phones")
    )

    by_contact = {}
    for cc in child_contacts:
        entry = by_contact.setdefault(
            cc.parent_contact_id,
            {"parent_contact": cc.parent_contact, "children": [], "roles": set()},
        )
        entry["children"].append(child_by_id[cc.child_id])
        entry["roles"].add(cc.role)

    called_parent_ids = set(
        RescheduleCallLog.objects.filter(lesson=lesson, parent_contact__isnull=False).values_list(
            "parent_contact_id", flat=True
        )
    )
    called_lead_ids = set(
        RescheduleCallLog.objects.filter(lesson=lesson, source_lead__isnull=False).values_list(
            "source_lead_id", flat=True
        )
    )

    role_labels = dict(ChildContact.Role.choices)
    contacts = []
    for parent_contact_id, entry in by_contact.items():
        parent_contact = entry["parent_contact"]
        phones = [phone.number for phone in parent_contact.phones.all()]
        whatsapp_number = parent_contact.whatsapp or (phones[0] if phones else "")
        contacts.append(
            {
                "contact_key": f"parent:{parent_contact_id}",
                "parent_contact_id": str(parent_contact_id),
                "source_lead_id": None,
                "parent_contact_name": parent_contact.full_name,
                "roles": [role_labels.get(role, role) for role in sorted(entry["roles"])],
                "children": [
                    {"id": str(child.id), "full_name": child.full_name}
                    for child in entry["children"]
                ],
                "phones": phones,
                "whatsapp_number": whatsapp_number,
                "whatsapp_link": _whatsapp_link(whatsapp_number, message),
                "called": parent_contact_id in called_parent_ids,
            }
        )

    for enrollment in trial_enrollments:
        lead = enrollment.source_lead
        contacts.append(
            {
                "contact_key": f"lead:{lead.id}",
                "parent_contact_id": None,
                "source_lead_id": str(lead.id),
                "parent_contact_name": lead.parent_name,
                "roles": ["Заявка на пробное"],
                "children": [
                    {"id": str(enrollment.child_id), "full_name": enrollment.child.full_name}
                ],
                "phones": [lead.phone],
                "whatsapp_number": lead.phone,
                "whatsapp_link": _whatsapp_link(lead.phone, message),
                "called": lead.id in called_lead_ids,
            }
        )
    contacts.sort(key=lambda c: c["parent_contact_name"])

    return {"message": message, "contacts": contacts}
