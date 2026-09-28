"""Переиспользуемая выборка истории посещений ребёнка.

TRU-55 показывает её в карточке ребёнка, а аналитика оттока сможет
использовать тот же queryset для признака учащающихся пропусков, не
воспроизводя правила tenant/date-фильтрации в своём домене.
"""

import datetime

from django.db.models import Count, Q
from django.utils import timezone

from .models import Attendance


def attendance_history_queryset(
    organization,
    child_id,
    *,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
):
    """История отметок ребёнка в локальных календарных границах организации."""
    tz = timezone.zoneinfo.ZoneInfo(organization.timezone or "Asia/Almaty")
    queryset = (
        Attendance.objects.for_tenant(organization)
        .filter(child_id=child_id)
        .select_related(
            "lesson",
            "lesson__group",
            "lesson__group__branch",
            "lesson__group__direction",
            "lesson__room",
            "lesson__teacher",
            "marked_by",
        )
        .order_by("-lesson__starts_at", "-created_at")
    )

    if date_from:
        starts_at = datetime.datetime.combine(date_from, datetime.time.min, tzinfo=tz)
        queryset = queryset.filter(lesson__starts_at__gte=starts_at)
    if date_to:
        ends_before = datetime.datetime.combine(
            date_to + datetime.timedelta(days=1), datetime.time.min, tzinfo=tz
        )
        queryset = queryset.filter(lesson__starts_at__lt=ends_before)
    return queryset


def attendance_history_summary(queryset):
    """Сводка по той же выборке, которая показана пользователю."""
    return queryset.order_by().aggregate(
        present=Count("id", filter=Q(status=Attendance.Status.PRESENT)),
        absent=Count("id", filter=Q(status=Attendance.Status.ABSENT)),
        makeup=Count("id", filter=Q(status=Attendance.Status.MAKEUP)),
    )
