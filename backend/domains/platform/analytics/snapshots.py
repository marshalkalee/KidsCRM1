"""Запись и чтение истории метрик-снимков (TRU-118)."""

from domains.platform.core.utils import today_for_org
from domains.platform.tenants.models import Branch, Organization

from .models import MetricSnapshot
from .registry import REGISTRY
from .scope import Scope


def snapshot_organization(organization) -> int:
    """Сохранить все снимки центра на сегодня: по организации и по каждому
    филиалу. Повтор в тот же день — перезапись, не дубль."""
    from . import metrics  # noqa: F401 — регистрирует базовые метрики

    today = today_for_org(organization)
    scopes = [(None, Scope(organization, None))] + [
        (branch, Scope(organization, (branch.pk,)))
        for branch in Branch.objects.for_tenant(organization).filter(is_active=True)
    ]
    saved = 0
    for metric in REGISTRY.values():
        if metric.kind != "snapshot":
            continue
        for branch, scope in scopes:
            MetricSnapshot.objects.update_or_create(
                organization=organization,
                metric=metric.name,
                branch=branch,
                date=today,
                defaults={"value": metric.value(scope, None)},
            )
            saved += 1
    return saved


def snapshot_all() -> int:
    return sum(snapshot_organization(org) for org in Organization.objects.all())


def history(metric, scope, period):
    """[(дата, значение)] за период — только когда выборка — вся
    организация или один филиал: проценты разных филиалов не складываются."""
    if scope.branch_ids is not None and len(scope.branch_ids) != 1:
        return None
    rows = MetricSnapshot.objects.for_tenant(scope.organization).filter(
        metric=metric.name, date__gte=period.start, date__lte=period.end
    )
    rows = (
        rows.filter(branch__isnull=True)
        if scope.branch_ids is None
        else rows.filter(branch_id=scope.branch_ids[0])
    )
    return list(rows.order_by("date").values_list("date", "value"))
