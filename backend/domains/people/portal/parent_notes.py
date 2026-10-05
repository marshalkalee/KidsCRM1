from django.utils import timezone

from domains.platform.core.utils import today_for_org
from domains.scheduling.attendance.models import ParentNote
from domains.scheduling.attendance.parent_notes import parent_notes_for_child

from .models import ParentNoteRead


def _serialize(note, read_ids):
    lesson = note.lesson
    starts_at = timezone.localtime(lesson.starts_at)
    return {
        "id": str(note.id),
        "kind": note.kind,
        "kind_display": note.get_kind_display(),
        "scope": note.scope,
        "scope_display": note.get_scope_display(),
        "body": note.body,
        "valid_until": note.valid_until,
        "lesson": {
            "id": str(lesson.id),
            "name": lesson.group.name if lesson.group_id else "Индивидуальное занятие",
            "starts_at": starts_at.isoformat(),
            "teacher": note.author.full_name,
        },
        "created_at": note.created_at,
        "read": note.id in read_ids,
    }


def feed(account, child):
    notes = list(parent_notes_for_child(child).order_by("-created_at"))
    read_ids = set(
        ParentNoteRead.objects.filter(account=account, note__in=notes).values_list(
            "note_id", flat=True
        )
    )
    rows = [_serialize(note, read_ids) for note in notes]
    today = today_for_org(child.organization)
    current_homework = next(
        (
            row
            for row in rows
            if row["kind"] == ParentNote.Kind.HOMEWORK
            and (row["valid_until"] is None or row["valid_until"] >= today)
        ),
        None,
    )
    return {
        "results": rows,
        "unread": sum(not row["read"] for row in rows),
        "current_homework": current_homework,
    }


def visible_to(child, note_id):
    return parent_notes_for_child(child).filter(pk=note_id).exists()


def mark_read(account, note_id):
    ParentNoteRead.objects.get_or_create(account=account, note_id=note_id)
