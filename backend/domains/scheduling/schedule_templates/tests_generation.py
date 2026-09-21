import datetime

from django.test import TestCase
from django.utils import timezone

from domains.platform.tenants.models import Branch, Direction, Organization, Room
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group
from domains.scheduling.schedule.models import Lesson
from domains.scheduling.schedule_templates.models import ScheduleTemplate, ScheduleTemplateSlot
from domains.scheduling.schedule_templates.services import generate_lessons_from_template


class LessonGenerationIdempotencyTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.branch = Branch.objects.create(organization=self.org, name="Главный")
        self.direction = Direction.objects.create(organization=self.org, name="Балет")
        self.room = Room.objects.create(
            organization=self.org, branch=self.branch, name="Зал 1", capacity=12
        )
        self.teacher = User.objects.create_user(
            phone="+77001234567",
            password="pass",
            organization=self.org,
            role="teacher",
        )
        self.group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.direction,
            name="Балет — Младшая",
            capacity=12,
        )
        self.template = ScheduleTemplate.objects.create(
            organization=self.org,
            group=self.group,
            valid_from=timezone.localdate(),
            generate_weeks_ahead=8,
        )
        ScheduleTemplateSlot.objects.create(
            organization=self.org,
            template=self.template,
            weekday=1,  # Вторник
            start_time=datetime.time(18, 0),
            duration_minutes=60,
            room=self.room,
            teacher=self.teacher,
        )
        ScheduleTemplateSlot.objects.create(
            organization=self.org,
            template=self.template,
            weekday=3,  # Четверг
            start_time=datetime.time(18, 0),
            duration_minutes=60,
            room=self.room,
            teacher=self.teacher,
        )

    def test_generates_lessons_for_8_weeks(self):
        result = generate_lessons_from_template(self.template)
        self.assertGreaterEqual(len(result["created"]), 14)

    def test_idempotent_triple_run(self):
        r1 = generate_lessons_from_template(self.template)
        r2 = generate_lessons_from_template(self.template)
        r3 = generate_lessons_from_template(self.template)

        self.assertGreater(len(r1["created"]), 0)
        self.assertEqual(len(r2["created"]), 0)
        self.assertEqual(len(r3["created"]), 0)
        self.assertGreater(r2["skipped"], 0)
        self.assertGreater(r3["skipped"], 0)

        total = Lesson.objects.filter(organization=self.org).count()
        self.assertEqual(total, len(r1["created"]))

    def test_modified_lesson_survives_generation(self):
        generate_lessons_from_template(self.template)

        lesson = Lesson.objects.filter(organization=self.org).first()
        lesson.is_modified = True
        lesson.status = Lesson.Status.RESCHEDULED
        lesson.save()
        original_starts_at = lesson.starts_at

        generate_lessons_from_template(self.template)

        lesson.refresh_from_db()
        self.assertEqual(lesson.starts_at, original_starts_at)
        self.assertEqual(lesson.status, Lesson.Status.RESCHEDULED)

    def test_past_dates_not_generated(self):
        past_template = ScheduleTemplate.objects.create(
            organization=self.org,
            group=self.group,
            valid_from=timezone.localdate() - datetime.timedelta(days=30),
            valid_until=timezone.localdate() - datetime.timedelta(days=1),
            generate_weeks_ahead=4,
        )
        ScheduleTemplateSlot.objects.create(
            organization=self.org,
            template=past_template,
            weekday=1,
            start_time=datetime.time(18, 0),
            duration_minutes=60,
        )
        result = generate_lessons_from_template(past_template)
        self.assertEqual(len(result["created"]), 0)
