import datetime

from django.test import TestCase
from django.utils import timezone

from domains.platform.tenants.models import Branch, Direction, Organization, Room
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group
from domains.scheduling.schedule_templates.models import ScheduleTemplate, ScheduleTemplateSlot
from domains.scheduling.schedule_templates.services import (
    generate_lessons_from_template,
    get_affected_future_lessons,
)


class ScheduleTemplateTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.branch = Branch.objects.create(organization=self.org, name="Главный")
        self.direction = Direction.objects.create(organization=self.org, name="Балет")
        self.room = Room.objects.create(
            organization=self.org, branch=self.branch, name="Зал 1", capacity=12
        )
        self.teacher = User.objects.create_user(
            phone="+77001234567", password="pass", organization=self.org, role="teacher"
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
            generate_weeks_ahead=2,
        )
        # Вт и Чт 18:00
        self.slot_tue = ScheduleTemplateSlot.objects.create(
            organization=self.org,
            template=self.template,
            weekday=1,  # Вторник
            start_time=datetime.time(18, 0),
            duration_minutes=60,
            room=self.room,
            teacher=self.teacher,
        )
        self.slot_thu = ScheduleTemplateSlot.objects.create(
            organization=self.org,
            template=self.template,
            weekday=3,  # Четверг
            start_time=datetime.time(18, 0),
            duration_minutes=60,
            room=self.room,
            teacher=self.teacher,
        )

    def test_template_is_active(self):
        self.assertTrue(self.template.is_active)

    def test_generate_creates_lessons(self):
        result = generate_lessons_from_template(self.template)
        self.assertGreater(len(result["created"]), 0)
        # За 2 недели — 2 вт + 2 чт = 4 занятия минимум
        self.assertGreaterEqual(len(result["created"]), 4)

    def test_generate_dry_run(self):
        result = generate_lessons_from_template(self.template, dry_run=True)
        self.assertGreater(len(result["created"]), 0)
        # dry_run — возвращает dict а не объект
        self.assertIsInstance(result["created"][0], dict)
        # Реальных занятий нет
        from domains.scheduling.schedule.models import Lesson

        self.assertEqual(Lesson.objects.count(), 0)

    def test_generate_skips_existing(self):
        generate_lessons_from_template(self.template)
        result = generate_lessons_from_template(self.template)
        self.assertEqual(len(result["created"]), 0)
        self.assertGreater(result["skipped"], 0)

    def test_modified_lessons_not_affected(self):
        generate_lessons_from_template(self.template)
        from domains.scheduling.schedule.models import Lesson

        lesson = Lesson.objects.first()
        lesson.is_modified = True
        lesson.save()
        affected = get_affected_future_lessons(self.template)
        modified_ids = [str(lesson.id)]
        for affected_lesson in affected:
            self.assertNotIn(str(affected_lesson.id), modified_ids)

    def test_tenant_isolation(self):
        org2 = Organization.objects.create(name="Other", slug="other")
        self.assertEqual(ScheduleTemplate.objects.for_tenant(org2).count(), 0)
