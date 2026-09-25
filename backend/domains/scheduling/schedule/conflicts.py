"""
Детект конфликтов расписания (TRU-46, ТЗ п. 4.2): один зал или один
преподаватель с пересекающимся по времени занятием — это ПРЕДУПРЕЖДЕНИЕ,
не запрет. Отменённые и перенесённые занятия конфликтов не создают — оба
статуса терминальны (ALLOWED_STATUS_TRANSITIONS) и означают, что занятие
больше не занимает зал/преподавателя в своё исходное время: отменённое не
состоится вообще, перенесённое переехало на новое время (у него уже есть
новое занятие — rescheduled_to, — которое участвует в проверке само по
себе, на своём времени). Индивидуальные занятия (group=None) участвуют
наравне с групповыми — конфликт определяется по room/teacher, а не по
группе.
"""

from collections import defaultdict

from django.db.models import Q

from .models import Lesson

# Статусы, которые фактически не занимают зал/преподавателя в указанное
# время — исходное время у них уже не актуально.
_INACTIVE_STATUSES = (Lesson.Status.CANCELLED, Lesson.Status.RESCHEDULED)


def _overlaps(a, b):
    return a.starts_at < b.ends_at and b.starts_at < a.ends_at


def find_conflicting_lessons(
    organization, *, starts_at, ends_at, room=None, teacher=None, exclude_id=None
):
    """Одна выборка — для проверки перед сохранением одного занятия
    (создание/перенос/изменение). Не тормозит сохранение (ТЗ, критерий
    приёмки): один индексированный запрос, не N+1."""
    if not room and not teacher:
        return Lesson.objects.none()

    qs = (
        Lesson.objects.for_tenant(organization)
        .exclude(status__in=_INACTIVE_STATUSES)
        .filter(starts_at__lt=ends_at, ends_at__gt=starts_at)
    )
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)

    resource_q = Q()
    if room:
        resource_q |= Q(room=room)
    if teacher:
        resource_q |= Q(teacher=teacher)

    return qs.filter(resource_q).select_related("room", "teacher", "group")


def compute_conflict_map(lessons):
    """`lessons` — уже загруженный в память список/queryset занятий одного
    окна (например, из LessonViewSet.get_queryset за диапазон дат) — без
    дополнительных запросов к БД, O(n²) внутри каждой группы по залу/
    преподавателю (группы на практике маленькие — десятки занятий в
    неделю на зал, не тысячи).

    Возвращает {lesson_id: {other_lesson_id, ...}} — только для занятий,
    у которых есть хотя бы один конфликт. Отменённые и перенесённые
    занятия исключаются и не могут ни с кем конфликтовать (см. модуль)."""
    active = [lesson for lesson in lessons if lesson.status not in _INACTIVE_STATUSES]

    by_room = defaultdict(list)
    by_teacher = defaultdict(list)
    for lesson in active:
        if lesson.room_id:
            by_room[lesson.room_id].append(lesson)
        if lesson.teacher_id:
            by_teacher[lesson.teacher_id].append(lesson)

    conflict_map = defaultdict(set)

    def mark_overlaps(groups):
        for items in groups.values():
            n = len(items)
            for i in range(n):
                for j in range(i + 1, n):
                    a, b = items[i], items[j]
                    if _overlaps(a, b):
                        conflict_map[a.id].add(b.id)
                        conflict_map[b.id].add(a.id)

    mark_overlaps(by_room)
    mark_overlaps(by_teacher)
    return dict(conflict_map)
