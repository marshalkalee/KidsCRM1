from django.db.models import Q

from .models import ParentNote


def parent_notes_for_child(child):
    """Public notes visible to one child's parents.

    This query intentionally starts from ParentNote.  It never reads Child's
    medical_notes or any internal staff communication.
    """

    return (
        ParentNote.objects.for_tenant(child.organization)
        .filter(
            Q(scope=ParentNote.Scope.CHILD, child=child)
            | Q(
                scope=ParentNote.Scope.GROUP,
                lesson__group__memberships__child=child,
                lesson__group__memberships__left_at__isnull=True,
                lesson__group__memberships__deleted_at__isnull=True,
            )
            | Q(
                scope=ParentNote.Scope.GROUP,
                lesson__enrollments__child=child,
                lesson__enrollments__cancelled_at__isnull=True,
                lesson__enrollments__deleted_at__isnull=True,
            )
        )
        .select_related("lesson", "lesson__group", "child", "author")
        .distinct()
    )
