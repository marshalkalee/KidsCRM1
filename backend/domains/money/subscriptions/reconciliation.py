"""
Фоновая сверка кэша с журналом (ТЗ п. 3.2, 11.3 — критерий приёмки MVP №3).
Один annotate-запрос на весь набор активных абонементов, не по одному —
иначе сама сверка станет нагрузкой на базу при росте объёмов.
"""

from django.db.models import Sum

from .models import BalanceDiscrepancy, Subscription
from .subscriptions import recompute_sessions_remaining


def reconcile_all_active_subscriptions() -> int:
    """Возвращает число найденных и исправленных расхождений."""
    qs = Subscription.objects.filter(
        status__in=[Subscription.Status.ACTIVE, Subscription.Status.FROZEN],
        subscription_type_version__is_unlimited=False,
    ).annotate(computed=Sum("ledger_entries__delta"))

    found = 0
    for subscription in qs.iterator():
        computed = subscription.computed or 0
        if computed != subscription.sessions_remaining_cache:
            BalanceDiscrepancy.objects.create(
                organization=subscription.organization,
                subscription=subscription,
                cached_value=subscription.sessions_remaining_cache,
                recomputed_value=computed,
            )
            subscription.sessions_remaining_cache = computed
            subscription.save(update_fields=["sessions_remaining_cache"])
            found += 1
    return found


def manual_recompute(subscription: Subscription) -> int | None:
    """Кнопка администратора при споре с родителем — пересчёт для одного
    конкретного абонемента, без ожидания ночной сверки. Расхождение пишется
    в тот же отчёт, что и у ночной сверки."""
    before = subscription.sessions_remaining_cache
    after = recompute_sessions_remaining(subscription)
    if before != after:
        BalanceDiscrepancy.objects.create(
            organization=subscription.organization,
            subscription=subscription,
            cached_value=before,
            recomputed_value=after,
        )
        subscription.sessions_remaining_cache = after
        subscription.save(update_fields=["sessions_remaining_cache"])
    return after
