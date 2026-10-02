"""
Базовые метрики (TRU-118). Отчёты M3 добавляют свои сюда же — рядом, а не
в своём view: так все отчёты считают «выручку» и «посещение» одинаково.

Откуда каждая цифра — в поле `source` и в ADR-0006, раздел «Источники».
"""

from decimal import Decimal

from django.db.models import Case, CharField, Value, When

from domains.money.payments.models import Payment
from domains.money.subscriptions.debt import debt_total
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
    RatioMetric(
        name="average_check",
        label="Средний чек",
        unit="money",
        source="Выручка / число оплат",
        min_history_days=FOUR_WEEKS,
        numerator="revenue",
        denominator="payments_count",
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
register(
    SnapshotMetric(
        name="group_fill",
        label="Заполняемость групп",
        unit="percent",
        source="groups.queries.with_members_count — как в списке групп",
        compute=_group_fill,
    )
)
