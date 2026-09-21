"""
Единая точка правды "абонемент ребёнка скоро заканчивается" (ТЗ п. 4.1,
4.4). Используется фильтром списка детей (domains.people.clients) и
будущим экраном «Продления» (Bekzat) — порог берётся из настроек
организации (`org_settings.get_org_setting`), не подставляется числом
здесь, иначе списки на двух экранах разойдутся при смене порога
владельцем (явное требование тикета "Фильтры списка детей").

Абонемент "заканчивается", когда осталось <= N дней ИЛИ (для не-безлимитных)
<= N занятий — см. DEFAULT_ORG_SETTINGS. Учитываются только ACTIVE
абонементы: замороженный не "заканчивается" прямо сейчас (родитель сам
решает, когда вернуться), исчерпанный/истёкший уже не активен.
"""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from domains.platform.tenants.org_settings import (
    SUBSCRIPTION_ENDING_DAYS_THRESHOLD,
    SUBSCRIPTION_ENDING_LESSONS_THRESHOLD,
    get_org_setting,
)

from .models import Subscription


def expiring_child_ids(organization, today=None):
    """Подзапрос id детей с активным абонементом, который скоро
    заканчивается — для `Child.objects.filter(id__in=expiring_child_ids(org))`,
    одним SQL-запросом (ТЗ п. 10.2)."""
    today = today or timezone.localdate()
    days_threshold = get_org_setting(organization, SUBSCRIPTION_ENDING_DAYS_THRESHOLD)
    lessons_threshold = get_org_setting(organization, SUBSCRIPTION_ENDING_LESSONS_THRESHOLD)

    ending_soon = Q(ends_on__lte=today + timedelta(days=days_threshold)) | Q(
        subscription_type_version__is_unlimited=False,
        sessions_remaining_cache__lte=lessons_threshold,
    )

    return (
        Subscription.objects.for_tenant(organization)
        .filter(status=Subscription.Status.ACTIVE)
        .filter(ending_soon)
        .values("child_id")
    )
