"""
Публичный срез предложения центра — задел под маркетплейс (TRU-177,
docs/marketplace-readiness.md). Наружу пока не открыт: адрес `catalog/`
описан как будущий v1.1 публичного API.

Только предложение центра: группы, которые центр сам отметил публичными,
их занятия со свободными местами, возраст, направление, филиал с адресом и
цены публичных типов абонементов. Ни детей, ни родителей, ни посещаемости,
ни денег семей — тот же принцип, что у агрегатов для ИИ (TRU-158).

Свободные места на занятие считаются одним запросом на весь период
(подзапросы вместо participants() на каждое занятие) — маркетплейс будет
опрашивать часто. Совпадение с Lesson.participants() проверяет тест.
"""

import datetime

from django.db.models import Count, IntegerField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce

from domains.money.subscriptions.models import SubscriptionType
from domains.scheduling.groups.models import GroupMembership
from domains.scheduling.schedule.models import Lesson, LessonEnrollment

# Поля ответа — белый список; тест следит, что сверх него ничего не уходит.
LESSON_FIELDS = (
    "lesson_id",
    "starts_at",
    "ends_at",
    "group",
    "branch",
    "capacity",
    "free_seats",
    "prices",
)


def _count(queryset):
    return Coalesce(
        Subquery(queryset.annotate(n=Count("id")).values("n")[:1], output_field=IntegerField()),
        Value(0),
    )


def _with_seats(lessons):
    members = GroupMembership.objects.filter(
        group_id=OuterRef("group_id"), left_at__isnull=True, deleted_at__isnull=True
    ).values("group_id")
    # Записанные поверх группы (отработки, пробные), кроме тех, кто и так в группе.
    in_group = GroupMembership.objects.filter(
        group_id=OuterRef(OuterRef("group_id")), left_at__isnull=True, deleted_at__isnull=True
    ).values("child_id")
    enrolled = (
        LessonEnrollment.objects.filter(lesson_id=OuterRef("pk"), cancelled_at__isnull=True)
        .exclude(child_id__in=Subquery(in_group))
        .values("lesson_id")
    )
    return lessons.annotate(taken=_count(members) + _count(enrolled))


def _prices(organization):
    """Публичные типы абонементов: (направления, филиалы, данные). Пустой
    список направлений или филиалов у типа — подходит ко всем."""
    rows = []
    for t in (
        SubscriptionType.objects.for_tenant(organization)
        .filter(is_public=True, is_active=True)
        .prefetch_related("directions", "branches")
        .order_by("price")
    ):
        rows.append(
            (
                {d.id for d in t.directions.all()},
                {b.id for b in t.branches.all()},
                {
                    "name": t.name,
                    "price": int(t.price),
                    "sessions": None if t.is_unlimited else t.quota_sessions,
                    "days": t.duration_days,
                },
            )
        )
    return rows


def offer(organization, date_from: datetime.date, date_to: datetime.date, *, include_private=False):
    """Занятия публичных групп за период: места, возраст, филиал, цены.
    include_private — только для замера скорости на всех группах."""
    lessons = (
        Lesson.objects.for_tenant(organization)
        .filter(
            deleted_at__isnull=True,
            group__isnull=False,
            starts_at__date__gte=date_from,
            starts_at__date__lte=date_to,
        )
        .exclude(status__in=["cancelled", "rescheduled"])
    )
    if not include_private:
        lessons = lessons.filter(group__is_public=True)
    lessons = _with_seats(lessons.select_related("group__branch", "group__direction"))
    prices = _prices(organization)
    result = []
    for lesson in lessons.order_by("starts_at", "id"):
        group = lesson.group
        result.append(
            {
                "lesson_id": str(lesson.id),
                "starts_at": lesson.starts_at.isoformat(),
                "ends_at": lesson.ends_at.isoformat(),
                "group": {
                    "id": str(group.id),
                    "name": group.name,
                    "description": group.description,
                    "direction": group.direction.name if group.direction_id else "",
                    "age_min": group.age_min,
                    "age_max": group.age_max,
                },
                "branch": {
                    "id": str(group.branch_id),
                    "name": group.branch.name,
                    "address": group.branch.address,
                },
                "capacity": group.capacity,
                "free_seats": max(group.capacity - lesson.taken, 0),
                "prices": [
                    data
                    for directions, branches, data in prices
                    if (not directions or group.direction_id in directions)
                    and (not branches or group.branch_id in branches)
                ],
            }
        )
    return result



def center_profile(organization) -> dict | None:
    """Карточка центра для каталога (TRU-179) — только опубликованная."""
    from .models import CenterProfile

    profile = CenterProfile.objects.for_tenant(organization).filter(is_published=True).first()
    if profile is None:
        return None
    return {
        "name": organization.name,
        "description": profile.description,
        "logo_url": profile.logo_url,
        "photo_urls": profile.photo_urls,
        "phone": profile.phone,
        "instagram": profile.instagram,
    }


__all__ = ["LESSON_FIELDS", "center_profile", "offer"]
