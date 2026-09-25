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


class LessonGenerationConflictTest(TestCase):
    """
    TRU-46, ТЗ п. 4.2: конфликт по залу/преподавателю при генерации из
    шаблона не блокирует её — попадает в результат (лог/список для
    администратора), генерация всё равно создаёт занятие.
    """

    def setUp(self):
        self.org = Organization.objects.create(name="True Ballet", slug="true-ballet")
        self.branch = Branch.objects.create(organization=self.org, name="Главный")
        self.direction = Direction.objects.create(organization=self.org, name="Балет")
        self.room = Room.objects.create(
            organization=self.org, branch=self.branch, name="Зал 1", capacity=12
        )
        self.teacher = User.objects.create_user(
            phone="+77001234568",
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
            generate_weeks_ahead=1,
        )
        # Слот на ближайший вторник, тот же зал и преподаватель, что и
        # заранее существующее занятие ниже — конфликт неизбежен.
        self.slot_weekday = 1
        ScheduleTemplateSlot.objects.create(
            organization=self.org,
            template=self.template,
            weekday=self.slot_weekday,
            start_time=datetime.time(18, 0),
            duration_minutes=60,
            room=self.room,
            teacher=self.teacher,
        )

        today = timezone.localdate()
        days_ahead = (self.slot_weekday - today.weekday()) % 7
        self.first_occurrence = today + datetime.timedelta(days=days_ahead)
        tz = timezone.get_current_timezone()
        conflict_start = datetime.datetime.combine(
            self.first_occurrence, datetime.time(18, 30), tzinfo=tz
        )
        self.pre_existing = Lesson.objects.create(
            organization=self.org,
            room=self.room,
            teacher=self.teacher,
            starts_at=conflict_start,
            ends_at=conflict_start + datetime.timedelta(hours=1),
        )

    def test_generation_does_not_skip_or_fail_on_conflict(self):
        result = generate_lessons_from_template(self.template)

        # Занятие всё равно создано, несмотря на конфликт (предупреждение,
        # не запрет) — сгенерированное + заранее существующее оба на месте.
        self.assertGreaterEqual(len(result["created"]), 1)
        self.assertEqual(
            Lesson.objects.filter(organization=self.org, group=self.group).count(),
            len(result["created"]),
        )

    def test_conflict_is_reported_in_result(self):
        result = generate_lessons_from_template(self.template)

        self.assertEqual(len(result["conflicts"]), 1)
        conflict = result["conflicts"][0]
        self.assertEqual(conflict["date"], self.first_occurrence)
        self.assertIn(self.pre_existing.id, conflict["conflicts_with"])

    def test_conflicting_generated_lesson_appears_in_conflicts_endpoint(self):
        from rest_framework.test import APIClient
        from rest_framework_simplejwt.tokens import RefreshToken

        generate_lessons_from_template(self.template)

        owner = User.objects.create_user(
            phone="+77001234569",
            password="pass",
            organization=self.org,
            role="owner",
        )
        client = APIClient()
        refresh = RefreshToken.for_user(owner)
        refresh["organization_id"] = str(self.org.id)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        response = client.get(
            "/api/v1/schedule/conflicts/",
            {
                "date_from": self.first_occurrence.isoformat(),
                "date_to": self.first_occurrence.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 2)  # сгенерированное + заранее существующее
