"""
Общее для веб-экранов групп (web_views.py, forms.py) и API (views.py,
serializers.py) — TRU-87: подсчёт состава, порог недозаполненности из
настроек организации, варианты выбора в форме. Одна реализация, чтобы веб
и frontend2 не разошлись.
"""

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone

from domains.platform.tenants.models import Branch, Direction
from domains.platform.tenants.org_settings import (
    GROUP_UNDERFILLED_PERCENT_THRESHOLD,
    get_org_setting,
)

User = get_user_model()


def with_members_count(qs):
    """members_count — дети в группе сейчас. Мягко удалённые записи состава
    не считаются (Count по связи обходит менеджер с deleted_at)."""
    return qs.annotate(
        members_count=Count(
            "memberships",
            filter=Q(memberships__left_at__isnull=True, memberships__deleted_at__isnull=True),
            distinct=True,
        )
    )


def fill_percent(group) -> int:
    if not group.capacity:
        return 0
    return round(group.members_count * 100 / group.capacity)


def underfilled_threshold(organization) -> int:
    """Порог «группа недозаполнена» — из настроек организации (экран
    «Организация»), не своё число."""
    return get_org_setting(organization, GROUP_UNDERFILLED_PERCENT_THRESHOLD)


def is_underfilled(group, threshold) -> bool:
    # Закрытая или приостановленная группа не «недозаполнена» — она не набирает.
    return group.status == group.Status.ACTIVE and fill_percent(group) < threshold


def branch_choices(organization, current=None):
    """Активные филиалы + текущий филиал группы, даже если он уже в архиве
    (TRU-77: иначе группу с архивным филиалом нельзя было сохранить)."""
    condition = Q(is_active=True)
    if current is not None:
        condition |= Q(pk=current.pk)
    return Branch.objects.for_tenant(organization).filter(condition)


def direction_choices(organization, current=None):
    condition = Q(is_active=True)
    if current is not None:
        condition |= Q(pk=current.pk)
    return Direction.objects.for_tenant(organization).filter(condition)


def teacher_choices(organization):
    return User.objects.filter(organization=organization, role=User.Role.TEACHER)


def active_template(group):
    """Действующий шаблон расписания из prefetch_related("schedule_templates__slots")."""
    today = timezone.localdate()
    templates = [
        t
        for t in group.schedule_templates.all()
        if t.valid_from <= today and (t.valid_until is None or t.valid_until >= today)
    ]
    return max(templates, key=lambda t: t.valid_from, default=None)
