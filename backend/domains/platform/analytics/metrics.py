"""
Базовые метрики (TRU-118). Отчёты M3 добавляют свои сюда же — рядом, а не
в своём view: так все отчёты считают «выручку» и «посещение» одинаково.

Откуда каждая цифра — в поле `source` и в ADR-0006, раздел «Источники».
"""

from decimal import Decimal

from django.db.models import Case, CharField, OuterRef, Subquery, Value, When

from domains.money.payments.models import Payment
from domains.money.subscriptions.debt import debt_structure, debt_total
from domains.money.subscriptions.models import Subscription
from domains.people.clients.models import Child
from domains.platform.leads.models import Lead, LeadKind
from domains.scheduling.attendance.models import Attendance
from domains.scheduling.groups.models import Group
from domains.scheduling.groups.queries import with_members_count

from .registry import EventMetric, RatioMetric, SnapshotMetric, count, register, total

# Четыре недели — меньше не видно ни недельного ритма, ни сравнения
# «к прошлому периоду»: отчёт скажет «данных пока мало».
FOUR_WEEKS = 28

VISITED = [Attendance.Status.PRESENT, Attendance.Status.MAKEUP]

# Деньги от новых клиентов или от продлений: абонемент, проданный как
# продление (renewed_from), — продление (TRU-123, структура выручки).
CLIENT_KIND = Case(
    When(subscription__renewed_from__isnull=False, then=Value("renewal")),
    default=Value("new"),
    output_field=CharField(),
)
# То же для продажи абонемента (TRU-124, средний чек).
SALE_CLIENT_KIND = Case(
    When(renewed_from__isnull=False, then=Value("renewal")),
    default=Value("new"),
    output_field=CharField(),
)
# Источник клиента — источник первой новой заявки, из которой пришёл ребёнок
# (как отчёт TRU-116). Нет заявки (пришёл до CRM, импорт) — «не указан».
CLIENT_SOURCE = Subquery(
    Lead.objects.filter(converted_child=OuterRef("child_id"), kind=LeadKind.NEW)
    .order_by("created_at")
    .values("source_id")[:1]
)
SALE_DIMENSIONS = {
    "branch": "branch_id",
    "direction": "direction_id",
    "subscription_type": "subscription_type_version__subscription_type_id",
    "client": SALE_CLIENT_KIND,
    "source": CLIENT_SOURCE,
}
LESSON_DIMENSIONS = {
    "branch": "lesson__group__branch_id",
    "direction": "lesson__group__direction_id",
    "group": "lesson__group_id",
    "teacher": "lesson__teacher_id",
}


def confirmed_payments(scope):
    # То же правило, что subscriptions.debt.paid_sum: только подтверждённые,
    # не отменённые — выручка дашборда = сумма оплат в карточках.
    qs = Payment.objects.for_tenant(scope.organization).filter(status=Payment.Status.CONFIRMED)
    return scope.filter(qs, "subscription__branch_id")


def sold_subscriptions(scope):
    """Проданные абонементы — по дате продажи (created_at), цена со скидкой."""
    qs = Subscription.objects.for_tenant(scope.organization)
    return scope.filter(qs, "branch_id")


def attendance_marks(scope):
    # lesson__organization — вроде бы лишнее условие, но без него Postgres не
    # может взять индекс занятий (organization, starts_at) и читает все
    # занятия подряд.
    qs = Attendance.objects.for_tenant(scope.organization).filter(
        lesson__organization=scope.organization, lesson__deleted_at__isnull=True
    )
    return scope.filter(qs, "lesson__group__branch_id")


def visits(scope):
    return attendance_marks(scope).filter(status__in=VISITED)


def absences(scope):
    return attendance_marks(scope).filter(status=Attendance.Status.ABSENT)


def new_leads(scope):
    qs = Lead.objects.for_tenant(scope.organization).filter(kind=LeadKind.NEW)
    return scope.filter(qs, "branch_id")


def _debt(scope):
    return debt_total(scope.organization, branch_ids=scope.branch_ids)


def _debt_age(key):
    def compute(scope):
        return debt_structure(scope.organization, branch_ids=scope.branch_ids)["by_age"][key]

    return compute


def children_in_scope(scope):
    """Активные дети (статус «активен»). В выборке филиалов — те, у кого
    есть абонемент в этих филиалах: у ребёнка нет своего филиала."""
    qs = Child.objects.for_tenant(scope.organization).filter(status=Child.Status.ACTIVE)
    if scope.branch_ids is not None:
        qs = qs.filter(
            id__in=Subscription.objects.for_tenant(scope.organization)
            .filter(branch_id__in=scope.branch_ids)
            .values("child_id")
        )
    return qs


def _debtors_share(scope):
    """Доля должников среди активных детей, %. Должник — тот же, что на
    экране «Задолженности» (subscriptions.debt)."""
    debtors = debt_structure(scope.organization, branch_ids=scope.branch_ids)["child_ids"]
    active = set(children_in_scope(scope).values_list("id", flat=True))
    if not active:
        return None
    return round(Decimal(len(debtors & active)) * 100 / Decimal(len(active)), 1)


def _group_fill(scope):
    """Заполняемость — по той же формуле, что список групп (TRU-40/87):
    дети в группах сейчас / вместимость активных групп."""
    groups = scope.filter(
        with_members_count(
            Group.objects.for_tenant(scope.organization).filter(status=Group.Status.ACTIVE)
        ),
        "branch_id",
    )
    members = capacity = 0
    for group in groups.only("capacity"):
        members += group.members_count
        capacity += group.capacity or 0
    if not capacity:
        return None
    return round(Decimal(members) * 100 / Decimal(capacity), 1)


register(
    EventMetric(
        name="revenue",
        label="Выручка",
        unit="money",
        source="Оплаты: подтверждённые, не отменённые (payments), по дате оплаты",
        min_history_days=FOUR_WEEKS,
        queryset=confirmed_payments,
        date_field="paid_at",
        aggregate=total("amount"),
        breakdowns={
            "method": "method",
            "branch": "subscription__branch_id",
            "direction": "subscription__direction_id",
            "subscription_type": "subscription__subscription_type_version__subscription_type_id",
            "client": CLIENT_KIND,
        },
    )
)
register(
    EventMetric(
        name="payments_count",
        label="Оплат",
        unit="count",
        source="Оплаты: подтверждённые, не отменённые",
        min_history_days=FOUR_WEEKS,
        queryset=confirmed_payments,
        date_field="paid_at",
        aggregate=count(),
        breakdowns={"method": "method", "branch": "subscription__branch_id"},
    )
)
register(
    EventMetric(
        name="sales_amount",
        label="Продано на сумму",
        unit="money",
        source="Абонементы: цена со скидкой, по дате продажи",
        min_history_days=FOUR_WEEKS,
        queryset=sold_subscriptions,
        date_field="created_at",
        aggregate=total("price"),
        breakdowns=SALE_DIMENSIONS,
    )
)
register(
    EventMetric(
        name="sales_count",
        label="Продано абонементов",
        unit="count",
        source="Абонементы: по дате продажи",
        min_history_days=FOUR_WEEKS,
        queryset=sold_subscriptions,
        date_field="created_at",
        aggregate=count(),
        breakdowns=SALE_DIMENSIONS,
    )
)
register(
    EventMetric(
        name="discount_total",
        label="Скидки",
        unit="money",
        source="Абонементы: сумма скидок, по дате продажи",
        min_history_days=FOUR_WEEKS,
        queryset=sold_subscriptions,
        date_field="created_at",
        aggregate=total("discount_amount"),
        breakdowns={**SALE_DIMENSIONS, "discount_reason": "discount_reason"},
    )
)
# Средний чек — средняя сумма проданного абонемента (TRU-124, ТЗ раздел 7),
# а не средняя оплата: при оплате частями средняя оплата занижает чек.
register(
    RatioMetric(
        name="average_check",
        label="Средний чек",
        unit="money",
        source="Сумма проданных абонементов / их число, по дате продажи",
        min_history_days=FOUR_WEEKS,
        numerator="sales_amount",
        denominator="sales_count",
    )
)
register(
    EventMetric(
        name="visits",
        label="Посещений",
        unit="count",
        source="Посещаемость: «был» и «отработка», по дате занятия",
        min_history_days=FOUR_WEEKS,
        queryset=visits,
        date_field="lesson__starts_at",
        aggregate=count(),
        breakdowns=LESSON_DIMENSIONS,
    )
)
register(
    EventMetric(
        name="attendance_marks",
        label="Отметок посещаемости",
        unit="count",
        source="Посещаемость: все отметки (был, не был, отработка)",
        min_history_days=FOUR_WEEKS,
        queryset=attendance_marks,
        date_field="lesson__starts_at",
        aggregate=count(),
        breakdowns={"status": "status", **LESSON_DIMENSIONS},
    )
)
register(
    EventMetric(
        name="absences",
        label="Пропусков",
        unit="count",
        source="Посещаемость: «не был», по дате занятия",
        min_history_days=FOUR_WEEKS,
        queryset=absences,
        date_field="lesson__starts_at",
        aggregate=count(),
        breakdowns={"reason": "absence_reason", **LESSON_DIMENSIONS},
    )
)
register(
    RatioMetric(
        name="attendance_rate",
        label="Доля посещений",
        unit="percent",
        source="Посещения / все отметки",
        min_history_days=FOUR_WEEKS,
        numerator="visits",
        denominator="attendance_marks",
        scale=100,
    )
)
register(
    EventMetric(
        name="active_children",
        label="Ходили на занятия",
        unit="count",
        source="Посещаемость: разные дети с хотя бы одним посещением",
        min_history_days=FOUR_WEEKS,
        queryset=visits,
        date_field="lesson__starts_at",
        aggregate=count("child_id", distinct=True),
        breakdowns={"branch": "lesson__group__branch_id"},
    )
)
register(
    EventMetric(
        name="new_leads",
        label="Новых заявок",
        unit="count",
        source="Заявки: новые продажи (без продлений), по дате создания",
        min_history_days=FOUR_WEEKS,
        queryset=new_leads,
        date_field="created_at",
        aggregate=count(),
        breakdowns={"branch": "branch_id", "source": "source_id", "direction": "direction_id"},
    )
)
register(
    SnapshotMetric(
        name="debt_total",
        label="Задолженность",
        unit="money",
        source="subscriptions.debt — та же цифра, что итог экрана «Задолженности»",
        compute=_debt,
    )
)
for key, label in (
    ("0_30", "Долг до 30 дней"),
    ("31_60", "Долг 31–60 дней"),
    ("over_60", "Долг больше 60 дней"),
):
    register(
        SnapshotMetric(
            name=f"debt_age_{key}",
            label=label,
            unit="money",
            source="subscriptions.debt — давность как на экране «Задолженности»",
            compute=_debt_age(key),
        )
    )
register(
    SnapshotMetric(
        name="debtors_share",
        label="Доля должников",
        unit="percent",
        source="Активные дети с долгом (subscriptions.debt) / активные дети",
        compute=_debtors_share,
    )
)
register(
    SnapshotMetric(
        name="group_fill",
        label="Заполняемость групп",
        unit="percent",
        source="groups.queries.with_members_count — как в списке групп",
        compute=_group_fill,
    )
)
