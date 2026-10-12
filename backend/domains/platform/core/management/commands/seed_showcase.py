"""
Витрина: отдельный «живой» центр для показа, со своими логинами на каждую
роль. Всё, что умеет seed_demo (филиалы, группы, семьи, абонементы, заявки,
продления), плюс то, без чего экраны выглядят пустыми:

- прошедшие занятия за три недели с посещаемостью (у пары детей — серия
  пропусков), вчерашние отмечены не все — для уведомлений;
- заморозки абонементов;
- пожелания в комментариях заявок — для подбора группы ИИ.

    python manage.py seed_showcase
    python manage.py seed_showcase --reset     # старую в архив, собрать заново

Пароль у всех — DemoKids2026. Только в разработке или на демо-сервере
(DEMO_DATA_ALLOWED=true в backend/.env).
"""

import datetime

from django.conf import settings
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from domains.money.subscriptions.freezes import freeze_subscription
from domains.money.subscriptions.models import Subscription
from domains.platform.leads.models import Lead
from domains.platform.tenants import onboarding
from domains.platform.tenants.models import Organization
from domains.scheduling.attendance.models import Attendance
from domains.scheduling.groups.models import GroupMembership
from domains.scheduling.schedule.models import Lesson
from domains.scheduling.schedule_templates.models import ScheduleTemplate, ScheduleTemplateSlot
from domains.scheduling.schedule_templates.services import generate_lessons_from_template

from .seed_demo import Command as DemoCommand
from .seed_demo import User

ORG_NAME = "Dance Kids Almaty"
ORG_SLUG = "dance-kids-almaty"
PASSWORD = "DemoKids2026"
OWNER = ("+77770000001", "Сауле Бекмуханова")
STAFF = [
    ("+77770000002", "Ержан Толеуов", User.Role.MANAGER),
    ("+77770000003", "Айнур Касымова", User.Role.ADMIN),
    ("+77770000004", "Гаухар Жунусова", User.Role.ACCOUNTANT),
]
# Пожелания родителей — по ним ИИ выбирает группу.
WISHES = [
    "Удобно только по субботам, в будни мама работает до 19:00",
    "После 17:00, раньше не успевают из школы",
    "Хотят в одну группу со старшей сестрой",
    "Нужно рядом с Орбитой, живут в Орбите-3",
    "Ребёнок стеснительный, лучше небольшая группа",
    "Утром в выходные, по будням кружок английского",
    "Занимались балетом год в другой студии",
]
ABSENCE_REASONS = [
    Attendance.AbsenceReason.ILLNESS,
    Attendance.AbsenceReason.ILLNESS,
    Attendance.AbsenceReason.FAMILY,
    Attendance.AbsenceReason.NO_REASON,
]


class Command(DemoCommand):
    help = "Демо-центр для показа с логинами всех ролей (разработка или демо-сервер)."
    teacher_phone = "+7777001{:04d}"

    def add_arguments(self, parser):
        parser.add_argument("--children", type=int, default=140)
        parser.add_argument("--seed", type=int, default=77)
        parser.add_argument(
            "--reset", action="store_true", help="Старую витрину в архив и собрать заново."
        )
        parser.add_argument(
            "--extras",
            action="store_true",
            help="Дополнить готовую витрину: задачи, объявления, запросы родителей, "
            "рассылки, профиль центра, импорт (showcase_extras.py).",
        )

    def handle(self, *args, children, seed, reset, extras=False, **options):
        if not settings.DEMO_DATA_ALLOWED:
            raise CommandError(
                "seed_showcase — только для разработки или демо-сервера (DEMO_DATA_ALLOWED=true)."
            )
        if extras:
            from domains.platform.core.showcase_extras import Extras

            org = Organization.objects.filter(slug=ORG_SLUG).first()
            if org is None:
                raise CommandError("Витрины нет — сначала seed_showcase без --extras.")
            Extras(org, self.stdout.write).run()
            return
        phones = [OWNER[0], *(phone for phone, *_ in STAFF)]
        existing = Organization.objects.filter(slug=ORG_SLUG).first()
        if existing and not reset:
            self.stdout.write(f"«{ORG_NAME}» уже есть — пропускаю (--reset, чтобы собрать заново).")
            self.print_logins()
            return
        if existing:
            # Удалить нельзя — занятия, оплаты и журнал защищены от удаления.
            # Прежнюю витрину отправляем в архив: другое имя, свободные телефоны.
            stamp = timezone.now().strftime("%d%H%M")  # телефон — до 20 символов
            self.stdout.write(f"Прежняя витрина → архив ({stamp})…")
            for user in User.objects.filter(organization=existing):
                user.phone = f"{user.phone}-{stamp}"
                user.is_active = False
                user.save(update_fields=["phone", "is_active"])
            existing.slug = f"{ORG_SLUG}-{stamp}"
            existing.name = f"{ORG_NAME} (архив {stamp})"
            existing.is_active = False
            existing.save(update_fields=["slug", "name", "is_active"])
        if User.objects.filter(phone__in=phones).exists():
            raise CommandError("Телефоны витрины заняты пользователями другой организации.")

        with transaction.atomic():
            org = Organization.objects.create(name=ORG_NAME, slug=ORG_SLUG)
            owner = User.objects.create_user(
                phone=OWNER[0],
                password=PASSWORD,
                full_name=OWNER[1],
                organization=org,
                role=User.Role.OWNER,
            )
            for phone, name, role in STAFF:
                User.objects.create_user(
                    phone=phone, password=PASSWORD, full_name=name, organization=org, role=role
                )
            onboarding.confirm_organization(org)
            onboarding.finish(org)

        # Основу собирает seed_demo — теми же сервисами, что приложение.
        super().handle(phone=OWNER[0], children=children, seed=seed)
        org.refresh_from_db()
        for teacher in User.objects.filter(organization=org, role=User.Role.TEACHER):
            teacher.set_password(PASSWORD)
            teacher.save(update_fields=["password"])

        with transaction.atomic():
            self.seed_weekend(org)
            marked = self.seed_past_lessons(org, owner)
            frozen = self.seed_freezes(org, owner)
            wishes = self.seed_wishes(org, owner)
        self.stdout.write(
            self.style.SUCCESS(
                f"Прошлых отметок: {marked}, заморозок: {frozen}, пожеланий в заявках: {wishes}."
            )
        )
        self.print_logins()

    def print_logins(self):
        self.stdout.write(f"\nВход (пароль у всех {PASSWORD}):")
        self.stdout.write(f"  Владелец      {OWNER[0]}  {OWNER[1]}")
        for phone, name, role in STAFF:
            self.stdout.write(f"  {User.Role(role).label:<13} {phone}  {name}")
        teacher = User.objects.filter(phone=self.teacher_phone.format(1)).first()
        if teacher:
            self.stdout.write(
                f"  Преподаватель {teacher.phone}  {teacher.full_name} (и …0002–0006)"
            )

    # --- субботние занятия ---------------------------------------------------

    def seed_weekend(self, org):
        """У части групп третье занятие в субботу утром — родители просят."""
        templates = list(
            ScheduleTemplate.objects.for_tenant(org).select_related("group").order_by("group__name")
        )
        for index, template in enumerate(self.rng.sample(templates, k=min(6, len(templates)))):
            first = template.slots.first()
            ScheduleTemplateSlot.objects.create(
                organization=org,
                template=template,
                weekday=5,
                # One distinct Saturday hour per group: the optional showcase
                # lessons cannot conflict by room or by teacher.
                start_time=datetime.time(9 + index, 0),
                duration_minutes=60,
                room=first.room if first else None,
                teacher=first.teacher if first else None,
            )
            generate_lessons_from_template(template)

    # --- прошедшие занятия и посещаемость -----------------------------------

    def seed_past_lessons(self, org, owner):
        """Три недели назад по вчера — по слотам шаблонов, как делал бы
        генератор. Отметки — через Attendance.mark (списание с абонемента)."""
        tz = timezone.get_current_timezone()
        today = timezone.localdate()
        yesterday = today - datetime.timedelta(days=1)
        # Два «пропадающих» ребёнка — серия пропусков для «Перед звонком».
        members = GroupMembership.objects.for_tenant(org).filter(left_at__isnull=True)
        truants = set(
            self.rng.sample(
                list(members.values_list("child_id", flat=True)), k=min(4, members.count())
            )
        )
        marked = 0
        templates = (
            ScheduleTemplate.objects.for_tenant(org)
            .select_related("group")
            .prefetch_related("slots")
        )
        for template in templates:
            roster = list(
                GroupMembership.objects.for_tenant(org)
                .filter(group=template.group, left_at__isnull=True)
                .select_related("child")
            )
            for days_ago in range(21, 0, -1):
                day = today - datetime.timedelta(days=days_ago)
                for slot in template.slots.all():
                    if day.weekday() != slot.weekday:
                        continue
                    starts = datetime.datetime.combine(day, slot.start_time, tzinfo=tz)
                    lesson = Lesson.objects.create(
                        organization=org,
                        group=template.group,
                        schedule_slot=slot,
                        room=slot.room,
                        teacher=slot.teacher,
                        starts_at=starts,
                        ends_at=starts + datetime.timedelta(minutes=slot.duration_minutes),
                    )
                    # Вчера: у части занятий отметка не закончена.
                    unfinished = day == yesterday and self.rng.random() < 0.6
                    for index, membership in enumerate(roster):
                        if membership.joined_at > day:
                            continue
                        if unfinished and index >= len(roster) // 2:
                            break
                        absent = (
                            membership.child_id in truants and days_ago <= 12
                        ) or self.rng.random() < 0.12
                        attendance, _ = Attendance.objects.get_or_create(
                            lesson=lesson,
                            child=membership.child,
                            defaults={"organization": org, "status": Attendance.Status.ABSENT},
                        )
                        attendance.mark(
                            Attendance.Status.ABSENT if absent else Attendance.Status.PRESENT,
                            actor=slot.teacher or owner,
                            absence_reason=self.rng.choice(ABSENCE_REASONS) if absent else "",
                        )
                        marked += 1
        return marked

    # --- заморозки ----------------------------------------------------------

    def seed_freezes(self, org, owner):
        today = timezone.localdate()
        active = list(
            Subscription.objects.for_tenant(org)
            .filter(status=Subscription.Status.ACTIVE)
            .select_related("subscription_type_version")
            .order_by("id")[:40]
        )
        frozen = 0
        for subscription in self.rng.sample(active, k=min(4, len(active))):
            start = today - datetime.timedelta(days=self.rng.randint(0, 3))
            try:
                freeze_subscription(
                    subscription,
                    actor=owner,
                    starts_on=start,
                    ends_on=start + datetime.timedelta(days=self.rng.choice([7, 10, 14])),
                    reason=self.rng.choice(
                        ["Болезнь, справка", "Уезжают к бабушке", "Отпуск семьи"]
                    ),
                )
            except ValueError:
                continue
            frozen += 1
        return frozen

    # --- пожелания в заявках ------------------------------------------------

    def seed_wishes(self, org, owner):
        leads = list(
            Lead.objects.for_tenant(org)
            .filter(
                kind=Lead.Kind.NEW, status__in=["new", "contacted", "trial_scheduled", "thinking"]
            )
            .order_by("created_at")
        )
        picked = self.rng.sample(leads, k=min(len(leads), 14))
        for lead in picked:
            lead.comments.create(organization=org, author=owner, text=self.rng.choice(WISHES))
        return len(picked)
