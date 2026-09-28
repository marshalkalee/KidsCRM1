"""«Занятие без абонемента» (ТЗ п. 4.3). Флаг и заглушка задачи уже
существуют на стороне Дарьи (Attendance.no_subscription_flag,
platform.tasks.services.create_admin_task_for_missing_subscription,
TRU-50/52) — здесь не дублируем, а читаем и переиспользуем её же
публичный, идемпотентный Attendance.mark()."""

from django.db import transaction
from django.db.models import Count, Min

from .sales import sell_subscription


def children_without_subscription(organization):
    """Рабочий список: ребёнок, сколько занятий без абонемента, с какой
    даты. Источник — Attendance (сторона Дарьи), не собственная модель."""
    from domains.scheduling.attendance.models import Attendance

    return (
        Attendance.objects.for_tenant(organization)
        .filter(no_subscription_flag=True, status=Attendance.Status.PRESENT)
        .values("child_id", "child__full_name")
        .annotate(lessons_count=Count("id"), since=Min("lesson__starts_at"))
        .order_by("since")
    )


def total_unpaid_lessons(organization) -> int:
    """Итоговая цифра для владельца — сколько занятий без оплаты сейчас."""
    from domains.scheduling.attendance.models import Attendance

    return (
        Attendance.objects.for_tenant(organization)
        .filter(
            no_subscription_flag=True,
            status=Attendance.Status.PRESENT,
        )
        .count()
    )


@transaction.atomic
def sell_and_cover(child, *, actor, **sale_kwargs):
    """Продажа абонемента + закрытие уже проведённых занятий без
    абонемента задним числом. Не переизобретаем списание — просто зовём
    Attendance.mark() ещё раз на каждой затронутой записи: её же
    идемпотентная _consume() сама подхватит новый абонемент, при нехватке
    занятий сама корректно остановится на SUBSCRIPTION_EXHAUSTED."""
    from domains.scheduling.attendance.models import Attendance

    subscription, payment = sell_subscription(actor=actor, child=child, **sale_kwargs)

    affected = Attendance.objects.filter(
        organization=subscription.organization,
        child=child,
        no_subscription_flag=True,
        status=Attendance.Status.PRESENT,
        lesson__starts_at__gte=subscription.starts_on,
    ).order_by("lesson__starts_at")

    covered = 0
    for attendance in affected:
        attendance.mark(attendance.status, actor=actor)
        if attendance.consumed_from_subscription:
            covered += 1

    subscription.refresh_from_db()
    return subscription, payment, covered
