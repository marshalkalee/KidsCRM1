import datetime

from django.utils import timezone

from domains.scheduling.schedule.conflicts import find_conflicting_lessons
from domains.scheduling.schedule.models import Lesson


def generate_lessons_from_template(template, *, dry_run=False):
    today = timezone.localdate()
    until = today + datetime.timedelta(weeks=template.generate_weeks_ahead)

    if template.valid_until:
        until = min(until, template.valid_until)

    start_from = max(today, template.valid_from)

    created = []
    skipped = 0
    # Конфликты (TRU-46, ТЗ п. 4.2) не блокируют генерацию — попадают сюда
    # для лога задачи и остаются видны в /api/v1/schedule/conflicts/ как
    # обычные сохранённые занятия. Только для реальной генерации — сухой
    # прогон ничего не сохраняет, проверять там нечего.
    conflicts = []

    for slot in template.slots.all():
        current = start_from
        while current <= until:
            if current.weekday() == slot.weekday:
                lesson_date = current
                start_dt = datetime.datetime.combine(
                    lesson_date,
                    slot.start_time,
                    tzinfo=timezone.get_current_timezone(),
                )
                end_dt = start_dt + datetime.timedelta(minutes=slot.duration_minutes)

                # Не создаём если занятие уже существует для этого слота
                exists = Lesson.objects.filter(
                    organization=template.organization,
                    group=template.group,
                    schedule_slot=slot,
                    starts_at__date=lesson_date,
                ).exists()

                if exists:
                    skipped += 1
                else:
                    if not dry_run:
                        lesson = Lesson.objects.create(
                            organization=template.organization,
                            group=template.group,
                            schedule_slot=slot,
                            room=slot.room,
                            teacher=slot.teacher,
                            starts_at=start_dt,
                            ends_at=end_dt,
                            is_modified=False,
                        )
                        created.append(lesson)

                        conflicting = find_conflicting_lessons(
                            template.organization,
                            starts_at=start_dt,
                            ends_at=end_dt,
                            room=slot.room,
                            teacher=slot.teacher,
                            exclude_id=lesson.id,
                        )
                        conflicting_ids = list(conflicting.values_list("id", flat=True))
                        if conflicting_ids:
                            conflicts.append(
                                {
                                    "lesson_id": lesson.id,
                                    "date": lesson_date,
                                    "room": str(slot.room) if slot.room else None,
                                    "teacher": str(slot.teacher) if slot.teacher else None,
                                    "conflicts_with": conflicting_ids,
                                }
                            )
                    else:
                        created.append(
                            {
                                "date": lesson_date,
                                "weekday": slot.get_weekday_display(),
                                "start_time": slot.start_time,
                                "room": str(slot.room) if slot.room else None,
                                "teacher": str(slot.teacher) if slot.teacher else None,
                            }
                        )
            current += datetime.timedelta(days=1)

    return {"created": created, "skipped": skipped, "conflicts": conflicts}


def get_affected_future_lessons(template):
    today = timezone.localdate()
    return Lesson.objects.filter(
        organization=template.organization,
        group=template.group,
        schedule_slot__template=template,
        starts_at__date__gt=today,
        is_modified=False,
    )


def cancel_future_lessons(template):
    return get_affected_future_lessons(template).delete()
