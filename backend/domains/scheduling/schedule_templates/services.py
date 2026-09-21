import datetime

from django.utils import timezone

from domains.scheduling.schedule.models import Lesson


def generate_lessons_from_template(template, *, dry_run=False):
    today = timezone.localdate()
    until = today + datetime.timedelta(weeks=template.generate_weeks_ahead)

    if template.valid_until:
        until = min(until, template.valid_until)

    start_from = max(today, template.valid_from)

    created = []
    skipped = 0

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

    return {"created": created, "skipped": skipped}


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
