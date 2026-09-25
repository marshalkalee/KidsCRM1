"""
Демо-данные для разработки (TRU-89): «живой» центр, чтобы экраны
frontend2 смотрели на десятках строк, а не на трёх тестовых записях.

    python manage.py seed_demo                       # организация владельца +77011234567
    python manage.py seed_demo --phone +7701… --children 200

Пишет через те же сервисы, что приложение: абонементы — sell_subscription
(оплата, журнал занятий, аудит), уроки — generate_lessons_from_template.
Детерминированно (--seed) и один раз на организацию: повторный запуск
ничего не дублирует (метка в Organization.settings["demo_seed"]).
Только DEBUG — в проде команда откажется работать.
"""

import datetime
import random
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from domains.money.subscriptions.sales import sell_subscription
from domains.money.subscriptions.subscription_types import create_type
from domains.people.clients.models import (
    Child,
    ChildContact,
    CommunicationLog,
    ContactPhone,
    ParentContact,
)
from domains.platform.tenants.models import Branch, Direction, Room
from domains.platform.tenants.working_hours import default_working_hours
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.schedule_templates.models import ScheduleTemplate, ScheduleTemplateSlot
from domains.scheduling.schedule_templates.services import generate_lessons_from_template

User = get_user_model()
MARKER = "demo_seed"

BRANCHES = [
    ("Центр на Абая", "пр. Абая, 150, 2 этаж", "+77272501010"),
    ("Орбита", "мкр. Орбита-2, 15", "+77272502020"),
    ("Алмалы", "ул. Жибек Жолы, 64", "+77272503030"),
]
DIRECTIONS = [
    # название, короткое (для групп), цвет, возраст, филиалы (индексы BRANCHES)
    ("Классический балет", "Балет", "#e8998d", 4, 14, (0, 1, 2)),
    ("Растяжка", "Растяжка", "#8bc6a0", 5, 16, (0, 1)),
    ("Хореография", "Хореография", "#8e9ae0", 6, 14, (0, 2)),
    ("Гимнастика", "Гимнастика", "#f0b86e", 4, 10, (1, 2)),
    ("Современный танец", "Contemporary", "#c48fd6", 9, 17, (0,)),
]
SHORT_NAMES = {name: short for name, short, *_ in DIRECTIONS}
TEACHERS = [
    "Динара Сейтказы",
    "Алия Жаксыбекова",
    "Мадина Оспанова",
    "Ольга Ким",
    "Сабина Нурланова",
    "Жанна Абенова",
]
SUBSCRIPTION_TYPES = [
    # название, цена, занятий (None — безлимит), дней
    ("8 занятий", 25000, 8, 30),
    ("12 занятий", 34000, 12, 30),
    ("Безлимит на месяц", 45000, None, 30),
    ("Разовое занятие", 4000, 1, 7),
]
GIRLS = [
    "Аружан",
    "Айгерим",
    "Амина",
    "Дана",
    "Асель",
    "Томирис",
    "Алиса",
    "Мира",
    "Сафия",
    "Айлин",
    "Камила",
    "Зарина",
    "Ева",
    "Милана",
    "Адель",
    "Жасмин",
    "София",
    "Аяулым",
]
BOYS = ["Данияр", "Алихан", "Санжар", "Тимур", "Арсен", "Нурислам", "Эмир", "Алан", "Марк"]
SURNAMES = [
    ("Ахметов", "Ахметова"),
    ("Серикбаев", "Серикбаева"),
    ("Нурланов", "Нурланова"),
    ("Касымов", "Касымова"),
    ("Жумабаев", "Жумабаева"),
    ("Оспанов", "Оспанова"),
    ("Тулегенов", "Тулегенова"),
    ("Иванов", "Иванова"),
    ("Ким", "Ким"),
    ("Абенов", "Абенова"),
    ("Садыков", "Садыкова"),
    ("Бекова", "Бекова"),
    ("Мусин", "Мусина"),
    ("Исаев", "Исаева"),
    ("Смагулов", "Смагулова"),
]
MOTHERS = ["Гульмира", "Айжан", "Динара", "Салтанат", "Жанар", "Мария", "Елена", "Асем", "Карлыгаш"]
FATHERS = ["Ерлан", "Марат", "Бауыржан", "Данияр", "Алексей", "Нурлан", "Азамат", "Руслан"]
MEDICAL = [
    "Аллергия на цитрусовые",
    "Плоскостопие, без прыжков на жёсткой поверхности",
    "Астма, ингалятор в рюкзаке",
    "После перелома руки — без упора на правую",
]
LEAVE_REASONS = ["Переезд", "Перешли в другую студию", "Не подходит время", "Финансы"]
NOTES = [
    ("call", "Напомнили про оплату, обещали занести в пятницу"),
    ("whatsapp", "Отправили расписание на следующий месяц"),
    ("call", "Мама спрашивала про выступление — рассказали про костюмы"),
    ("comment", "Пропустила две недели по болезни, справка будет"),
    ("whatsapp", "Прислали фото с отчётного концерта"),
    ("call", "Уточнили, можно ли перевести в группу постарше"),
    ("comment", "Папа забирает по вторникам, мама — по четвергам"),
    ("whatsapp", "Напомнили продлить абонемент"),
]


class Command(BaseCommand):
    help = "Наполняет организацию демо-данными для разработки (только DEBUG)."

    def add_arguments(self, parser):
        parser.add_argument("--phone", default="+77011234567", help="Телефон владельца.")
        parser.add_argument("--children", type=int, default=150)
        parser.add_argument("--seed", type=int, default=2026)

    def handle(self, *args, phone, children, seed, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo — только для разработки (DEBUG=True).")
        owner = User.objects.filter(phone=phone, role=User.Role.OWNER).first()
        if owner is None or owner.organization is None:
            raise CommandError(f"Нет владельца организации с телефоном {phone}.")
        org = owner.organization
        if (org.settings or {}).get(MARKER):
            self.stdout.write(f"«{org.name}» уже наполнена демо-данными — пропускаю.")
            return

        self.rng = random.Random(seed)
        self.org = org
        self.owner = owner
        self.today = timezone.localdate()
        self.used_phones = set(ContactPhone.objects.values_list("number", flat=True))
        self.filled = {}
        with transaction.atomic():
            branches = self.seed_branches()
            directions = self.seed_directions(branches)
            teachers = self.seed_teachers()
            versions = self.seed_subscription_types()
            groups = self.seed_groups(branches, directions, teachers)
            kids = self.seed_families(children, groups)
            self.seed_subscriptions(kids, versions)
            self.seed_communications(kids)
            org.settings = {**(org.settings or {}), MARKER: str(self.today)}
            org.save(update_fields=["settings"])
        lessons = self.seed_lessons(groups)
        self.stdout.write(
            self.style.SUCCESS(
                f"«{org.name}»: {len(branches)} филиала, {len(directions)} направлений, "
                f"{len(groups)} групп, {len(kids)} детей, {lessons} занятий."
            )
        )

    # --- справочники --------------------------------------------------------

    def seed_branches(self):
        branches = []
        for name, address, phone in BRANCHES:
            branch, _ = Branch.objects.get_or_create(
                organization=self.org,
                name=name,
                defaults={
                    "address": address,
                    "phone": phone,
                    "working_hours": {
                        **default_working_hours(),
                        "sat": {"closed": False, "open": "10:00", "close": "15:00"},
                    },
                },
            )
            for room_name, capacity in (("Большой зал", 20), ("Малый зал", 10)):
                Room.objects.get_or_create(
                    organization=self.org,
                    branch=branch,
                    name=room_name,
                    defaults={"capacity": capacity},
                )
            branches.append(branch)
        return branches

    def seed_directions(self, branches):
        directions = []
        for name, _short, color, age_min, age_max, branch_idx in DIRECTIONS:
            direction, _ = Direction.objects.get_or_create(
                organization=self.org,
                name=name,
                defaults={"color": color, "age_min": age_min, "age_max": age_max},
            )
            direction.branches.add(*(branches[i] for i in branch_idx))
            directions.append(direction)
        return directions

    def seed_teachers(self):
        teachers = []
        for index, full_name in enumerate(TEACHERS, start=1):
            teacher, created = User.objects.get_or_create(
                phone=f"+7700900{index:04d}",
                defaults={
                    "full_name": full_name,
                    "organization": self.org,
                    "role": User.Role.TEACHER,
                },
            )
            if created:
                teacher.set_password("demo-teacher-1")
                teacher.save(update_fields=["password"])
            teachers.append(teacher)
        return teachers

    def seed_subscription_types(self):
        from domains.money.subscriptions.models import SubscriptionType

        versions = []
        for name, price, quota, days in SUBSCRIPTION_TYPES:
            existing = SubscriptionType.objects.for_tenant(self.org).filter(name=name).first()
            sub_type = existing or create_type(
                self.org,
                name=name,
                price=price,
                is_unlimited=quota is None,
                quota_sessions=quota,
                duration_days=days,
            )
            versions.append(sub_type.versions.latest())
        return versions

    # --- группы и расписание ------------------------------------------------

    def seed_groups(self, branches, directions, teachers):
        groups = []
        for direction in directions:
            for branch in direction.branches.filter(id__in=[b.id for b in branches]):
                # Две возрастные группы на направление в филиале.
                span = direction.age_max - direction.age_min
                bands = [
                    (direction.age_min, direction.age_min + span // 2),
                    (direction.age_min + span // 2 + 1, direction.age_max),
                ]
                short = SHORT_NAMES.get(direction.name, direction.name)
                for age_min, age_max in bands:
                    group, created = Group.objects.get_or_create(
                        organization=self.org,
                        branch=branch,
                        direction=direction,
                        name=f"{short} {age_min}–{age_max}",
                        defaults={
                            "capacity": self.rng.choice([10, 12, 12, 15]),
                            "age_min": age_min,
                            "age_max": age_max,
                        },
                    )
                    if created:
                        group.teachers.add(*self.rng.sample(teachers, self.rng.choice([1, 1, 2])))
                    groups.append(group)
        return groups

    def seed_lessons(self, groups):
        created = 0
        for index, group in enumerate(groups):
            if ScheduleTemplate.objects.filter(group=group).exists():
                continue
            template = ScheduleTemplate.objects.create(
                organization=self.org,
                group=group,
                valid_from=self.today - datetime.timedelta(days=30),
                generate_weeks_ahead=3,
            )
            rooms = list(Room.objects.for_tenant(self.org).filter(branch=group.branch))
            teacher = group.teachers.first()
            # Разводим группы одного филиала по времени, чтобы не было накладок.
            start_hour = 15 + index % 4
            for weekday in ((0, 2), (1, 3), (0, 3), (2, 4))[index % 4]:
                ScheduleTemplateSlot.objects.create(
                    organization=self.org,
                    template=template,
                    weekday=weekday,
                    start_time=datetime.time(start_hour, 0),
                    duration_minutes=60,
                    room=rooms[index % len(rooms)] if rooms else None,
                    teacher=teacher,
                )
            created += len(generate_lessons_from_template(template)["created"])
        return created

    # --- семьи ----------------------------------------------------------------

    def phone(self):
        while True:
            number = f"+77{self.rng.choice(['01', '02', '05', '07', '47', '75', '77'])}" + "".join(
                str(self.rng.randint(0, 9)) for _ in range(7)
            )
            if number not in self.used_phones:
                self.used_phones.add(number)
                return number

    def seed_families(self, total, groups):
        kids = []
        while len(kids) < total:
            surname_m, surname_f = self.rng.choice(SURNAMES)
            mother = ParentContact.objects.create(
                organization=self.org,
                full_name=f"{surname_f} {self.rng.choice(MOTHERS)}",
            )
            mother_phone = self.phone()
            ContactPhone.objects.create(parent_contact=mother, number=mother_phone)
            if self.rng.random() < 0.6:
                mother.whatsapp = mother_phone
                mother.save(update_fields=["whatsapp"])
            father = None
            if self.rng.random() < 0.35:
                father = ParentContact.objects.create(
                    organization=self.org,
                    full_name=f"{surname_m} {self.rng.choice(FATHERS)}",
                )
                ContactPhone.objects.create(parent_contact=father, number=self.phone())

            siblings = self.rng.choices([1, 2, 3], weights=[72, 23, 5])[0]
            for _ in range(siblings):
                kid = self.make_child(surname_m, surname_f, groups)
                payer_is_father = father is not None and self.rng.random() < 0.3
                ChildContact.objects.create(
                    child=kid,
                    parent_contact=mother,
                    role=ChildContact.Role.MOTHER,
                    is_payer=not payer_is_father,
                    is_primary_contact=True,
                )
                if father:
                    ChildContact.objects.create(
                        child=kid,
                        parent_contact=father,
                        role=ChildContact.Role.FATHER,
                        is_payer=payer_is_father,
                    )
                kids.append(kid)
        return kids

    def make_child(self, surname_m, surname_f, groups):
        girl = self.rng.random() < 0.78  # балетная студия — в основном девочки
        first_name = self.rng.choice(GIRLS if girl else BOYS)
        # Только группы со свободными местами — как при записи через API.
        free = [g for g in groups if self.filled.get(g.pk, 0) < g.capacity]
        group = self.rng.choice(free or groups)
        self.filled[group.pk] = self.filled.get(group.pk, 0) + 1
        age = self.rng.randint(group.age_min, group.age_max)
        birth_date = self.today - datetime.timedelta(days=age * 365 + self.rng.randint(0, 360))
        status = self.rng.choices(
            [Child.Status.ACTIVE, Child.Status.PAUSED, Child.Status.LEFT], weights=[85, 8, 7]
        )[0]
        kid = Child.objects.create(
            organization=self.org,
            full_name=f"{surname_f if girl else surname_m} {first_name}",
            birth_date=birth_date,
            gender=Child.Gender.FEMALE if girl else Child.Gender.MALE,
            status=status,
            leave_reason=self.rng.choice(LEAVE_REASONS) if status == Child.Status.LEFT else "",
            medical_notes=self.rng.choice(MEDICAL) if self.rng.random() < 0.1 else "",
            consent_given=self.rng.random() < 0.9,
        )
        kid.directions.add(group.direction)
        joined = self.today - datetime.timedelta(days=self.rng.randint(10, 400))
        GroupMembership.objects.create(
            organization=self.org,
            group=group,
            child=kid,
            joined_at=joined,
            left_at=(
                self.today - datetime.timedelta(days=5) if status == Child.Status.LEFT else None
            ),
        )
        kid.demo_group = group
        return kid

    # --- деньги и коммуникации ---------------------------------------------

    def seed_subscriptions(self, kids, versions):
        methods = ["kaspi_transfer", "kaspi_transfer", "cash", "card"]
        for kid in kids:
            if kid.status != Child.Status.ACTIVE or self.rng.random() > 0.85:
                continue
            version = self.rng.choices(versions, weights=[50, 25, 15, 10])[0]
            # Часть абонементов начата давно — заканчиваются, попадут в «Продления».
            days_ago = self.rng.randint(0, version.duration_days - 1)
            started = self.today - datetime.timedelta(days=days_ago)
            price = Decimal(version.price)
            paid = self.rng.choices(
                [price, price, price / 2, Decimal(0)], weights=[55, 15, 18, 12]
            )[0]
            sell_subscription(
                actor=self.owner,
                child=kid,
                subscription_type_version=version,
                direction=kid.demo_group.direction,
                branch=kid.demo_group.branch,
                starts_on=started,
                ends_on=started + datetime.timedelta(days=version.duration_days),
                paid_amount=paid.quantize(Decimal(1)),
                payment_method=self.rng.choice(methods),
            )

    def seed_communications(self, kids):
        for kid in self.rng.sample(kids, k=min(len(kids), 70)):
            link = ChildContact.objects.filter(child=kid).select_related("parent_contact").first()
            for _ in range(self.rng.randint(1, 3)):
                channel, note = self.rng.choice(NOTES)
                log = CommunicationLog.objects.create(
                    child=kid,
                    parent_contact=link.parent_contact if link else None,
                    channel=channel,
                    note=note,
                    author=self.owner,
                )
                # Раскидываем по последнему месяцу — лента выглядит живой.
                CommunicationLog.objects.filter(pk=log.pk).update(
                    created_at=timezone.now()
                    - datetime.timedelta(
                        days=self.rng.randint(0, 30), hours=self.rng.randint(0, 10)
                    )
                )
