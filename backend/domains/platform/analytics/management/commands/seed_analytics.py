"""
Сид целевого объёма для замера аналитики (TRU-118, ТЗ п. 10.2): 10
филиалов, 5000 детей, год истории — занятия, посещаемость, абонементы
каждый месяц, оплаты, заявки. Своя организация, другие не трогает.

    python manage.py seed_analytics            # ≈ 0,5 млн отметок, пара минут
    python manage.py seed_analytics --reset    # старую в архив, насидить заново

Замер — `python manage.py analytics_benchmark`.
"""

import random
import uuid
from datetime import datetime, time, timedelta

import pytz
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import connection, transaction

from domains.money.payments.models import Payment
from domains.money.subscriptions.models import Subscription
from domains.money.subscriptions.subscription_types import create_type
from domains.people.clients.models import Child
from domains.platform.leads.models import (
    Lead,
    LeadKind,
    LeadRejectionReason,
    LeadSource,
    LeadStatusChange,
)
from domains.platform.tenants.models import Branch, Direction, Organization
from domains.scheduling.attendance.models import Attendance
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.schedule.models import Lesson

SLUG = "analytics-volume"
BRANCHES = 10
CHILDREN = 5000
GROUP_SIZE = 20
DAYS = 365
BATCH = 5000
REJECTION_COMMENTS = [
    "Сказали, что дорого для двоих детей",
    "Хотят только по выходным",
    "Переезжают в другой район",
    "Ребёнок не захотел после пробного",
    "Нашли кружок рядом с домом",
    "Не отвечают на звонки",
]
DISCOUNT_REASONS = ["second_child", "large_family", "promotion", "staff"]
DIRECTIONS = ["Балет", "Хореография", "Гимнастика", "Акробатика", "Растяжка"]


class Command(BaseCommand):
    help = "Сид аналитики: 10 филиалов, 5000 детей, год истории (TRU-118)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true")
        parser.add_argument("--seed", type=int, default=118)

    def handle(self, *args, reset, seed, **options):
        random.seed(seed)
        organization = Organization.objects.filter(slug=SLUG).first()
        if organization and not reset:
            self.stdout.write("Уже насижено. --reset, чтобы пересоздать.")
            return
        if organization:
            self._wipe(organization)
        organization = Organization.objects.create(
            slug=SLUG, name="Аналитика — целевой объём", timezone="Asia/Almaty"
        )
        self.tz = pytz.timezone(organization.timezone)
        self.today = datetime.now(self.tz).date()
        self.first_day = self.today - timedelta(days=DAYS - 1)
        # created_at/paid_at проставляются «сейчас» даже в bulk_create — для
        # истории за год даём сиду самому задать дату.
        for model, name in (
            (Payment, "paid_at"),
            (Lead, "created_at"),
            (Subscription, "created_at"),
        ):
            model._meta.get_field(name).auto_now_add = False

        with transaction.atomic():
            owner = self._owner(organization)
            branches, directions, version = self._catalog(organization)
            children, groups = self._children_and_groups(organization, branches, directions)
            self._lessons_and_attendance(organization, groups)
            self._subscriptions_and_payments(organization, owner, version, groups)
            self._leads(organization, branches, directions, owner)
        with connection.cursor() as cursor:
            cursor.execute("ANALYZE")
        self.stdout.write(self.style.SUCCESS(f"Готово: organization={organization.pk}"))

    def _wipe(self, organization):
        # Удалять год истории по всем таблицам с PROTECT долго и хрупко —
        # старая организация уходит в архив под другим слагом, как «Dance
        # Kids Almaty (архив …)» в демо. Дев-база, не прод.
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        Organization.objects.filter(pk=organization.pk).update(
            slug=f"{SLUG}-{stamp}",
            name=f"{organization.name} (архив {stamp})",
            deleted_at=datetime.now(pytz.utc),
        )
        for index, user in enumerate(get_user_model().objects.filter(organization=organization)):
            user.phone, user.is_active = f"a{stamp}{index:03d}", False
            user.save(update_fields=["phone", "is_active"])

    def _owner(self, organization):
        User = get_user_model()
        owner = User.objects.create_user(
            phone="+77009990118",
            password="Analytics2026",
            full_name="Владелец (замер)",
            organization=organization,
            role=User.Role.OWNER,
        )
        # Преподаватели — для разрезов «по преподавателю» (TRU-120/121).
        self.teachers = [
            User.objects.create_user(
                phone=f"+7700999{1000 + i}",
                password=None,
                full_name=f"Преподаватель {i + 1:02d}",
                organization=organization,
                role=User.Role.TEACHER,
            )
            for i in range(25)
        ]
        # Менеджеры по продажам — для воронки «по ответственному» (TRU-115).
        self.managers = [
            User.objects.create_user(
                phone=f"+7700999{2000 + i}",
                password=None,
                full_name=f"Менеджер {i + 1}",
                organization=organization,
                role=User.Role.MANAGER,
            )
            for i in range(4)
        ]
        return owner

    def _catalog(self, organization):
        branches = [
            Branch.objects.create(organization=organization, name=f"Филиал {i:02d}")
            for i in range(1, BRANCHES + 1)
        ]
        directions = []
        for name in DIRECTIONS:
            direction = Direction.objects.create(organization=organization, name=name)
            direction.branches.set(branches)
            directions.append(direction)
        subscription_type = create_type(
            organization, name="8 занятий", price=30000, quota_sessions=8, duration_days=30
        )
        return branches, directions, subscription_type.versions.latest()

    def _children_and_groups(self, organization, branches, directions):
        children = Child.objects.bulk_create(
            [
                Child(
                    id=uuid.uuid4(),
                    organization=organization,
                    full_name=f"Ребёнок {i:04d}",
                    birth_date=self.today - timedelta(days=random.randint(4 * 365, 14 * 365)),
                    gender=random.choice(["male", "female"]),
                )
                for i in range(CHILDREN)
            ],
            batch_size=BATCH,
        )
        group_count = CHILDREN // GROUP_SIZE
        groups = Group.objects.bulk_create(
            [
                Group(
                    id=uuid.uuid4(),
                    organization=organization,
                    branch=branches[i % BRANCHES],
                    direction=directions[i % len(directions)],
                    name=f"Группа {i:03d}",
                    capacity=random.choice([20, 22, 25, 30]),
                )
                for i in range(group_count)
            ]
        )
        memberships = []
        departed_ids = []
        self.members = {}
        for index, child in enumerate(children):
            group = groups[index % group_count]
            # Треть детей пришла в течение года, часть ушла — состав меняется.
            joined = self.first_day + timedelta(days=random.choice([0, 0, random.randint(0, 300)]))
            left = (
                joined + timedelta(days=random.randint(60, 300)) if random.random() < 0.15 else None
            )
            if left and left >= self.today:
                left = None
            if left:
                departed_ids.append(child.id)
            memberships.append(
                GroupMembership(
                    id=uuid.uuid4(),
                    organization=organization,
                    group=group,
                    child=child,
                    joined_at=joined,
                    left_at=left,
                )
            )
            self.members.setdefault(group.id, []).append((child.id, joined, left))
        GroupMembership.objects.bulk_create(memberships, batch_size=BATCH)
        Child.objects.filter(pk__in=departed_ids).update(
            status=Child.Status.LEFT,
            leave_reason="Перестали посещать занятия",
        )
        self.stdout.write(f"  детей {len(children)}, групп {len(groups)}")
        return children, groups

    def _lessons_and_attendance(self, organization, groups):
        lessons, marks = [], []
        total_marks = 0
        for group in groups:
            weekdays = random.sample(range(6), 2)
            teacher = random.choice(self.teachers)
            hour = random.choice([10, 15, 16, 17, 18])
            day = self.first_day
            while day <= self.today:
                if day.weekday() in weekdays:
                    starts = self.tz.localize(datetime.combine(day, time(hour)))
                    cancelled = random.random() < 0.03
                    lesson = Lesson(
                        id=uuid.uuid4(),
                        organization=organization,
                        group=group,
                        # Иногда замена — чтобы у преподавателя были и чужие группы.
                        teacher=teacher if random.random() > 0.05 else random.choice(self.teachers),
                        starts_at=starts,
                        ends_at=starts + timedelta(hours=1),
                        status=Lesson.Status.CANCELLED if cancelled else Lesson.Status.COMPLETED,
                    )
                    lessons.append(lesson)
                    if not cancelled:
                        for child_id, joined, left in self.members[group.id]:
                            if joined <= day and (left is None or day < left):
                                roll = random.random()
                                # Перед уходом посещаемость заметно проседает. Это даёт
                                # реалистичную ретровыборку для калибровки TRU-122,
                                # а не искусственный одинаковый процент на всём году.
                                leaving_window = (
                                    left is not None and left - timedelta(days=21) <= day
                                )
                                status = (
                                    Attendance.Status.PRESENT
                                    if roll < (0.3 if leaving_window else 0.82)
                                    else Attendance.Status.MAKEUP
                                    if roll < (0.32 if leaving_window else 0.84)
                                    else Attendance.Status.ABSENT
                                )
                                marks.append(
                                    Attendance(
                                        id=uuid.uuid4(),
                                        organization=organization,
                                        lesson=lesson,
                                        child_id=child_id,
                                        status=status,
                                        absence_reason=(
                                            random.choices(
                                                ["illness", "family", "no_reason", ""],
                                                weights=[50, 20, 15, 15],
                                            )[0]
                                            if status == Attendance.Status.ABSENT
                                            else ""
                                        ),
                                        marked_at=starts,
                                    )
                                )
                day += timedelta(days=1)
            if len(marks) > 50_000:
                Lesson.objects.bulk_create(lessons, batch_size=BATCH)
                Attendance.objects.bulk_create(marks, batch_size=BATCH)
                total_marks += len(marks)
                lessons, marks = [], []
        Lesson.objects.bulk_create(lessons, batch_size=BATCH)
        Attendance.objects.bulk_create(marks, batch_size=BATCH)
        total_marks += len(marks)
        self.stdout.write(f"  отметок посещаемости {total_marks}")

    def _subscriptions_and_payments(self, organization, owner, version, groups):
        subscriptions, payments = [], []
        bigger = create_type(
            organization, name="12 занятий", price=40000, quota_sessions=12, duration_days=30
        ).versions.latest()
        for group in groups:
            for child_id, joined, left in self.members[group.id]:
                start = joined
                previous = None
                chosen = version if random.random() < 0.7 else bigger
                end_of_membership = left or self.today
                while start <= end_of_membership:
                    # Каждая десятая продажа — со скидкой (TRU-124, влияние скидок).
                    discount, reason = 0, ""
                    if random.random() < 0.1:
                        discount = int(chosen.price) // 10
                        reason = random.choice(DISCOUNT_REASONS)
                    subscription = Subscription(
                        id=uuid.uuid4(),
                        organization=organization,
                        child_id=child_id,
                        subscription_type_version=chosen,
                        # Цепочка «продлил → следующий абонемент» — для разреза
                        # «новые клиенты / продления» (TRU-123).
                        renewed_from=previous,
                        direction_id=group.direction_id,
                        branch_id=group.branch_id,
                        starts_on=start,
                        ends_on=start + timedelta(days=30),
                        status=(
                            Subscription.Status.ACTIVE
                            if start + timedelta(days=30) >= self.today
                            else Subscription.Status.EXPIRED
                        ),
                        list_price=chosen.price,
                        discount_amount=discount,
                        discount_reason=reason,
                        price=chosen.price - discount,
                        # Дата продажи — день начала абонемента, а не день сида.
                        created_at=self.tz.localize(datetime.combine(start, time(11))),
                    )
                    previous = subscription
                    subscriptions.append(subscription)
                    # 85% платят полностью, остальные частично или позже.
                    roll = random.random()
                    full = int(subscription.price)
                    amounts = [full] if roll < 0.85 else [full // 2] if roll < 0.95 else []
                    for amount in amounts:
                        paid_day = start + timedelta(days=random.randint(0, 3))
                        payments.append(
                            Payment(
                                id=uuid.uuid4(),
                                organization=organization,
                                subscription=subscription,
                                amount=amount,
                                method=random.choice(["kaspi_transfer", "cash", "card"]),
                                status=Payment.Status.CONFIRMED,
                                received_by=owner,
                                paid_at=self.tz.localize(
                                    datetime.combine(min(paid_day, self.today), time(12))
                                ),
                            )
                        )
                    start += timedelta(days=30)
        Subscription.objects.bulk_create(subscriptions, batch_size=BATCH)
        Payment.objects.bulk_create(payments, batch_size=BATCH)
        self.stdout.write(f"  абонементов {len(subscriptions)}, оплат {len(payments)}")

    def _leads(self, organization, branches, directions, owner):
        """Заявки проходят воронку по шагам (TRU-115): связались → пробное →
        пришёл → купил, на каждом шаге часть отваливается в «думает» или отказ,
        немногие покупают сразу после звонка."""
        S = Lead.Status
        leads, changes = [], []
        sources = list(LeadSource.objects.for_tenant(organization)) or [None]
        reasons = LeadRejectionReason.objects.for_tenant(organization).filter(kind=LeadKind.NEW)
        lost = reasons.filter(is_lost_contact=True).first()
        objections = list(reasons.filter(is_lost_contact=False)) or [None]
        lost = lost or objections[0]
        managers = self.managers

        def path():
            steps = [S.NEW]
            if random.random() > 0.72:
                return steps + [random.choice([S.REJECTED, S.NEW])]
            steps.append(S.CONTACTED)
            if random.random() < 0.08:
                return steps + [S.PURCHASED]
            if random.random() > 0.62:
                return steps + [random.choice([S.THINKING, S.REJECTED])]
            steps.append(S.TRIAL_SCHEDULED)
            if random.random() > 0.76:
                return steps + [random.choice([S.CONTACTED, S.REJECTED])]
            steps.append(S.TRIAL_ATTENDED)
            if random.random() < 0.55:
                return steps + [S.PURCHASED]
            return steps + [random.choice([S.THINKING, S.REJECTED])]

        for i in range(4000):
            created = self.tz.localize(
                datetime.combine(
                    self.first_day + timedelta(days=random.randint(0, DAYS - 1)), time(11)
                )
            )
            steps = path()
            if steps[-1] == S.NEW and len(steps) > 1:
                steps = steps[:-1]
            lead = Lead(
                id=uuid.uuid4(),
                organization=organization,
                kind=LeadKind.NEW,
                branch=random.choice(branches),
                direction=random.choice(directions),
                source=random.choices(sources, weights=range(len(sources), 0, -1))[0],
                assigned_to=random.choice(managers),
                parent_name=f"Родитель {i}",
                phone=f"+7701{i:07d}",
                child_name=f"Ребёнок заявки {i}",
                status=steps[-1],
                status_changed_at=created,
                created_at=created,
            )
            leads.append(lead)
            moment = created
            previous = ""
            for status in steps:
                reason, comment = None, ""
                if status == S.REJECTED:
                    # Не пришёл на пробное — чаще всего после записи (TRU-117).
                    reason = (
                        lost
                        if previous == S.TRIAL_SCHEDULED and random.random() < 0.6
                        else random.choice(objections)
                    )
                    lead.rejection_reason = reason
                    if random.random() < 0.3:
                        comment = random.choice(REJECTION_COMMENTS)
                        lead.rejection_comment = comment
                changes.append(
                    LeadStatusChange(
                        id=uuid.uuid4(),
                        organization=organization,
                        lead=lead,
                        from_status=previous,
                        to_status=status,
                        changed_by=owner,
                        changed_at=moment,
                        rejection_reason=reason,
                        comment=comment,
                    )
                )
                previous = status
                moment += timedelta(days=random.randint(1, 6))
        # Купившим — проданный абонемент, как при продаже из заявки (#104):
        # по нему считается средний чек источника (TRU-116).
        sold = list(Subscription.objects.for_tenant(organization).only("id", "price")[:2000])
        for lead in leads:
            if lead.status == S.PURCHASED and sold:
                lead.sold_subscription = random.choice(sold)
        Lead.objects.bulk_create(leads, batch_size=BATCH)
        LeadStatusChange.objects.bulk_create(changes, batch_size=BATCH)
        self.stdout.write(f"  заявок {len(leads)}")
