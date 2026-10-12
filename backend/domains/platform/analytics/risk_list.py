"""Риск-лист «в зоне ухода» (TRU-122).

Модуль только объединяет сигналы. Формулы остаются в доменах-источниках:
посещаемость — attendance_trends, продление — subscriptions.renewals,
задолженность — subscriptions.debt.

Дети, которые уже ушли по правилу оттока (analytics/churn.py, TRU-127),
сюда не попадают: их список — в отчёте «Отток».
"""

from decimal import Decimal

from django.db.models import Q

from domains.money.subscriptions.debt import debt_by_child
from domains.money.subscriptions.renewals import renewal_risk_by_child
from domains.people.clients.models import Child
from domains.platform.tenants.org_settings import (
    RISK_ABSENCE_CHANGE_PP_THRESHOLD,
    RISK_CURRENT_ABSENCES_MIN,
    get_org_setting,
)
from domains.scheduling.groups.models import GroupMembership

from .attendance_trends import child_attendance_deviation
from .churn import departed_child_ids
from .contacts import parent_contacts

SIGNAL_ATTENDANCE = "attendance"
SIGNAL_SUBSCRIPTION = "subscription"
SIGNAL_DEBT = "debt"


def _candidate_children(scope, attendance_child_ids=(), statuses=None):
    statuses = statuses or [Child.Status.ACTIVE, Child.Status.PAUSED, Child.Status.TRIAL]
    children = Child.objects.for_tenant(scope.organization).filter(status__in=statuses)
    if scope.branch_ids is not None:
        membership = Q(group_memberships__group__branch_id__in=scope.branch_ids)
        if Child.Status.LEFT not in statuses:
            membership &= Q(
                group_memberships__left_at__isnull=True,
                group_memberships__deleted_at__isnull=True,
            )
        children = children.filter(
            membership
            | Q(subscriptions__branch_id__in=scope.branch_ids)
            | Q(id__in=attendance_child_ids)
        )
    return children.distinct()


def _context_by_child(organization, child_ids):
    context = {child_id: {"branch": None, "direction": None} for child_id in child_ids}
    memberships = (
        GroupMembership.objects.for_tenant(organization)
        .filter(child_id__in=child_ids, left_at__isnull=True)
        .select_related("group__branch", "group__direction")
        .order_by("child_id", "joined_at")
    )
    for membership in memberships:
        row = context[membership.child_id]
        if row["branch"] is None:
            row["branch"] = membership.group.branch.name
            row["direction"] = membership.group.direction.name

    for child_id, contact in parent_contacts(organization, child_ids).items():
        context[child_id].update(contact)
    return context


def _attendance_signal(row, change_threshold, absences_min):
    return bool(
        row
        and row["has_baseline"]
        and row["absence_change_pp"] is not None
        and row["absence_change_pp"] >= change_threshold
        and row["absences"] >= absences_min
    )


def risk_list(scope, period):
    organization = scope.organization
    change_threshold = get_org_setting(organization, RISK_ABSENCE_CHANGE_PP_THRESHOLD)
    absences_min = get_org_setting(organization, RISK_CURRENT_ABSENCES_MIN)
    attendance_rows = {row["id"]: row for row in child_attendance_deviation(scope, period)}

    children = list(_candidate_children(scope, attendance_rows).only("id", "full_name", "status"))
    # Уже ушедшие (нет абонемента дольше порога оттока) — в отчёте «Отток»
    # (TRU-127), не здесь: риск-лист — про тех, кого ещё можно удержать.
    gone = departed_child_ids(organization, [child.id for child in children])
    children = [child for child in children if child.id not in gone]
    departed = list(
        _candidate_children(scope, attendance_rows, statuses=[Child.Status.LEFT]).only(
            "id", "full_name", "status"
        )
    )
    child_ids = {child.id for child in children}
    all_child_ids = child_ids | {child.id for child in departed}
    renewal = renewal_risk_by_child(organization, all_child_ids)
    debts = debt_by_child(organization, all_child_ids)
    context = _context_by_child(organization, child_ids)

    items = []
    signal_counts = {SIGNAL_ATTENDANCE: 0, SIGNAL_SUBSCRIPTION: 0, SIGNAL_DEBT: 0}
    for child in children:
        attendance = attendance_rows.get(str(child.id))
        signals = []
        if _attendance_signal(attendance, change_threshold, absences_min):
            signals.append(SIGNAL_ATTENDANCE)
        if child.id in renewal:
            signals.append(SIGNAL_SUBSCRIPTION)
        debt = debts.get(child.id, Decimal(0))
        if debt > 0:
            signals.append(SIGNAL_DEBT)
        if not signals:
            continue
        for signal in signals:
            signal_counts[signal] += 1
        score = len(signals)
        items.append(
            {
                "id": str(child.id),
                "name": child.full_name,
                "status": child.status,
                "level": "urgent" if score >= 2 else "attention",
                "score": score,
                "signals": signals,
                "attendance": attendance,
                "subscription": renewal.get(child.id),
                "debt": float(debt),
                **context[child.id],
            }
        )
    items.sort(
        key=lambda row: (
            -row["score"],
            -(
                (row["attendance"] or {}).get("absence_change_pp")
                if (row["attendance"] or {}).get("absence_change_pp") is not None
                else -1000
            ),
            -row["debt"],
            row["name"],
        )
    )
    urgent = sum(row["level"] == "urgent" for row in items)
    caught_departed = 0
    for child in departed:
        attendance = attendance_rows.get(str(child.id))
        caught_departed += bool(
            _attendance_signal(attendance, change_threshold, absences_min)
            or child.id in renewal
            or debts.get(child.id, Decimal(0)) > 0
        )
    return {
        "period": period.as_dict(),
        "thresholds": {
            "absence_change_pp": change_threshold,
            "minimum_absences": absences_min,
        },
        "summary": {
            "total": len(items),
            "urgent": urgent,
            "attention": len(items) - urgent,
            "financial": sum(
                SIGNAL_SUBSCRIPTION in row["signals"] or SIGNAL_DEBT in row["signals"]
                for row in items
            ),
            "active_children": len(children),
            "share_percent": round(len(items) * 100 / len(children), 1) if children else 0,
            "signals": signal_counts,
        },
        "retrospective": {
            "departed": len(departed),
            "caught": caught_departed,
            "catch_rate": (round(caught_departed * 100 / len(departed), 1) if departed else None),
        },
        "items": items,
    }
