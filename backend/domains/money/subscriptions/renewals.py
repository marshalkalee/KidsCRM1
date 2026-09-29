"""
Единая точка правды "абонемент ребёнка скоро заканчивается" (ТЗ п. 4.1,
4.4). Используется фильтром списка детей (domains.people.clients) и
экраном «Продления» (TRU-69) — порог берётся из настроек организации,
не подставляется числом здесь, иначе списки на двух экранах разойдутся
при смене порога владельцем.

Абонемент "заканчивается", когда осталось <= N дней ИЛИ (для
не-безлимитных) <= N занятий. Учитываются только ACTIVE абонементы.
«Сегодня» — дата центра (today_for_org), не сервера: сервер живёт в UTC,
и вечером по Алматы у него ещё вчера.

Условие одно, в двух формах: Q для списков (_ending_soon_condition) и
проверка одного абонемента (is_ending_soon) — для карточки. Менять вместе.
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import Q

from domains.platform.core.utils import today_for_org
from domains.platform.tenants.org_settings import (
    SUBSCRIPTION_ENDING_DAYS_THRESHOLD,
    SUBSCRIPTION_ENDING_LESSONS_THRESHOLD,
    get_org_setting,
)

from .models import RenewalContact, Subscription
from .sales import sell_subscription


def _thresholds(organization):
    return (
        get_org_setting(organization, SUBSCRIPTION_ENDING_DAYS_THRESHOLD),
        get_org_setting(organization, SUBSCRIPTION_ENDING_LESSONS_THRESHOLD),
    )


def _ending_soon_condition(organization, today):
    days_threshold, lessons_threshold = _thresholds(organization)
    return Q(ends_on__lte=today + timedelta(days=days_threshold)) | Q(
        subscription_type_version__is_unlimited=False,
        sessions_remaining_cache__lte=lessons_threshold,
    )


def is_ending_soon(subscription, today=None) -> bool:
    """То же условие, что _ending_soon_condition, для одного абонемента."""
    if subscription.status != Subscription.Status.ACTIVE:
        return False
    organization = subscription.organization
    today = today or today_for_org(organization)
    days_threshold, lessons_threshold = _thresholds(organization)
    if subscription.ends_on <= today + timedelta(days=days_threshold):
        return True
    remaining = subscription.sessions_remaining_cache
    return (
        not subscription.subscription_type_version.is_unlimited
        and remaining is not None
        and remaining <= lessons_threshold
    )


def expiring_child_ids(organization, today=None):
    """Подзапрос id детей с активным абонементом, который скоро
    заканчивается — для фильтра списка детей, одним SQL-запросом."""
    today = today or today_for_org(organization)
    return (
        Subscription.objects.for_tenant(organization)
        .filter(status=Subscription.Status.ACTIVE)
        .filter(_ending_soon_condition(organization, today))
        .values("child_id")
    )


def expiring_subscriptions(organization, *, branch=None, direction=None, group=None, today=None):
    """То же условие, что и expiring_child_ids, но полные объекты
    Subscription с фильтрами — для экрана «Продления»."""
    today = today or today_for_org(organization)
    qs = (
        Subscription.objects.for_tenant(organization)
        .filter(status=Subscription.Status.ACTIVE)
        .filter(_ending_soon_condition(organization, today))
        .select_related("child", "subscription_type_version", "direction", "branch")
    )
    if branch:
        qs = qs.filter(branch=branch)
    if direction:
        qs = qs.filter(direction=direction)
    if group:
        qs = qs.filter(
            child__group_memberships__group=group, child__group_memberships__left_at__isnull=True
        )
    return qs.order_by("ends_on")


def mark_contacted(subscription, *, actor, note=""):
    return RenewalContact.objects.create(
        organization=subscription.organization,
        subscription=subscription,
        contacted_by=actor,
        note=note,
    )


@transaction.atomic
def sell_renewal(old_subscription, **sale_kwargs):
    """sell_subscription() + явная связь со старым абонементом (ТЗ п. 5.3 —
    видно, какой абонемент сменился каким, задел под конверсию в M3)."""
    new_subscription, payment = sell_subscription(**sale_kwargs)
    new_subscription.renewed_from = old_subscription
    new_subscription.save(update_fields=["renewed_from"])
    return new_subscription, payment
