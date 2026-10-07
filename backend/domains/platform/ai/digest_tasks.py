"""Ручное превращение рекомендаций дайджеста в задачи (TRU-164).

Модель видит только обезличенные агрегаты. Конкретных детей для задач
удержания и продления этот модуль выбирает заново из CRM после нажатия
пользователя.
"""

import hashlib

from django.utils import timezone

from domains.people.clients.models import Child
from domains.platform.analytics.period import period_for
from domains.platform.analytics.risk_list import SIGNAL_SUBSCRIPTION, risk_list
from domains.platform.analytics.scope import Scope
from domains.platform.core.utils import today_for_org
from domains.platform.tasks.models import Task
from domains.platform.tasks.services import create_task
from domains.platform.tenants.models import Branch, Direction
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group, GroupMembership

from .models import AIDigest, AIRecommendationState

ALLOWED_TYPES = {
    Task.Type.RETENTION,
    Task.Type.RENEWAL_OFFER,
    Task.Type.CALL_BACK,
    Task.Type.OTHER,
}
REASONABLE_LEAVE_REASONS = (
    "переезд",
    "переех",
    "перерос",
    "возраст",
    "закончил",
    "завершил",
    "выпуск",
    "програм",
)


class DigestTaskError(ValueError):
    pass


def recommendation_fingerprint(item_id: str) -> str:
    return hashlib.sha256(item_id.encode()).hexdigest()


def find_item(digest: AIDigest, item_id: str) -> dict:
    item = next(
        (row for row in (digest.content or {}).get("items", []) if row["id"] == item_id), None
    )
    if item is None:
        raise DigestTaskError("Рекомендация не найдена.")
    return item


def is_dismissed(organization, item_id: str) -> bool:
    return (
        AIRecommendationState.objects.for_tenant(organization)
        .filter(
            function="digest",
            fingerprint=recommendation_fingerprint(item_id),
            status=AIRecommendationState.Status.DISMISSED,
        )
        .exists()
    )


def dismiss(organization, item: dict):
    fingerprint = recommendation_fingerprint(item["id"])
    state, _ = AIRecommendationState.objects.update_or_create(
        organization=organization,
        function="digest",
        fingerprint=fingerprint,
        defaults={
            "candidate_key": fingerprint,
            "status": AIRecommendationState.Status.DISMISSED,
            "payload": {"title": item.get("title", "")},
            "last_seen_at": timezone.now(),
        },
    )
    return state


def _admin_users(organization):
    return list(
        User.objects.filter(
            organization=organization,
            is_active=True,
            role__in=(User.Role.ADMIN, User.Role.MANAGER, User.Role.OWNER),
        )
        .prefetch_related("branches")
        .order_by("role", "full_name")
    )


def _child_branches(organization, child_ids):
    result = {}
    memberships = (
        GroupMembership.objects.for_tenant(organization)
        .filter(child_id__in=child_ids)
        .select_related("group__branch")
        .order_by("child_id", "-joined_at")
    )
    for membership in memberships:
        result.setdefault(str(membership.child_id), membership.group.branch)
    return result


def _default_assignee(users, branch, actor):
    if branch is not None:
        for user in users:
            if user.role == User.Role.ADMIN and any(
                item.id == branch.id for item in user.branches.all()
            ):
                return user
    return next((user for user in users if user.id == actor.id), users[0] if users else None)


def _reasonable_departure(reason: str) -> bool:
    normalized = reason.casefold()
    return any(fragment in normalized for fragment in REASONABLE_LEAVE_REASONS)


def _candidate_children(organization, task_type):
    period = period_for("month", today_for_org(organization))
    rows = risk_list(Scope(organization, None, []), period)["items"]
    if task_type == Task.Type.RENEWAL_OFFER:
        rows = [row for row in rows if SIGNAL_SUBSCRIPTION in row["signals"]]
    else:
        departed = Child.objects.for_tenant(organization).filter(status=Child.Status.LEFT)
        rows.extend(
            {
                "id": str(child.id),
                "name": child.full_name,
                "signals": ["left"],
            }
            for child in departed
            if not _reasonable_departure(child.leave_reason)
        )
    # Один ребёнок может одновременно попасть в риск-лист и список ушедших.
    return list({row["id"]: row for row in rows}.values())


def _scope_candidate_ids(organization, item, candidate_ids):
    """Сузить живых клиентов до филиала/направления/группы из фактов совета.

    Названия здесь берутся из подписей фактов, которые подставил наш код,
    а не из свободного текста модели.
    """
    labels = " ".join(evidence.get("label", "") for evidence in item.get("evidence", []))
    if not labels:
        return candidate_ids
    groups = [
        group.id
        for group in Group.objects.for_tenant(organization).select_related("branch")
        if group.name in labels and group.branch.name in labels
    ]
    branches = [
        branch.id for branch in Branch.objects.for_tenant(organization) if branch.name in labels
    ]
    directions = [
        direction.id
        for direction in Direction.objects.for_tenant(organization)
        if direction.name in labels
    ]
    if not (groups or branches or directions):
        return candidate_ids
    memberships = GroupMembership.objects.for_tenant(organization).filter(
        child_id__in=candidate_ids
    )
    if groups:
        memberships = memberships.filter(group_id__in=groups)
    else:
        if branches:
            memberships = memberships.filter(group__branch_id__in=branches)
        if directions:
            memberships = memberships.filter(group__direction_id__in=directions)
    return [str(child_id) for child_id in memberships.values_list("child_id", flat=True).distinct()]


def _source_key(item_id, task_type, child_id=None):
    target = child_id or "general"
    raw = f"{recommendation_fingerprint(item_id)}:{task_type}:{target}"
    return f"digest:{hashlib.sha256(raw.encode()).hexdigest()}"


def preview(digest, item, task_type, actor):
    if task_type not in ALLOWED_TYPES:
        raise DigestTaskError("Неизвестный тип задачи.")
    if is_dismissed(digest.organization, item["id"]):
        raise DigestTaskError("Эта рекомендация уже отмечена как неактуальная.")

    users = _admin_users(digest.organization)
    if not users:
        raise DigestTaskError("Нет активного администратора, которому можно поставить задачу.")
    candidates = (
        _candidate_children(digest.organization, task_type)
        if task_type in (Task.Type.RETENTION, Task.Type.RENEWAL_OFFER)
        else []
    )
    scoped_ids = set(
        _scope_candidate_ids(
            digest.organization,
            item,
            [row["id"] for row in candidates],
        )
    )
    candidates = [row for row in candidates if row["id"] in scoped_ids]
    children = {
        str(child.id): child
        for child in Child.objects.for_tenant(digest.organization).filter(
            id__in=[row["id"] for row in candidates]
        )
    }
    branches = _child_branches(digest.organization, children)
    rows = []
    if task_type in (Task.Type.RETENTION, Task.Type.RENEWAL_OFFER):
        for candidate in candidates:
            child = children.get(candidate["id"])
            if child is None:
                continue
            branch = branches.get(candidate["id"])
            assignee = _default_assignee(users, branch, actor)
            key = _source_key(item["id"], task_type, candidate["id"])
            rows.append(
                {
                    "child_id": candidate["id"],
                    "child_name": candidate["name"],
                    "branch_id": str(branch.id) if branch else None,
                    "branch_name": branch.name if branch else None,
                    "assignee_id": str(assignee.id),
                    "assignee_name": assignee.full_name,
                    "reason": _reason(candidate.get("signals", [])),
                    "already_exists": Task.objects.for_tenant(digest.organization)
                    .filter(type=task_type, source_key=key, status=Task.Status.OPEN)
                    .exists(),
                }
            )
    else:
        assignee = _default_assignee(users, None, actor)
        key = _source_key(item["id"], task_type)
        rows.append(
            {
                "child_id": None,
                "child_name": None,
                "branch_id": None,
                "branch_name": None,
                "assignee_id": str(assignee.id),
                "assignee_name": assignee.full_name,
                "reason": item.get("action", ""),
                "already_exists": Task.objects.for_tenant(digest.organization)
                .filter(type=task_type, source_key=key, status=Task.Status.OPEN)
                .exists(),
            }
        )
    return {
        "recommendation": {"id": item["id"], "title": item.get("title", "")},
        "task_type": task_type,
        "items": rows,
        "new_count": sum(not row["already_exists"] for row in rows),
        "assignees": [
            {"id": str(user.id), "name": user.full_name, "role": user.role} for user in users
        ],
    }


def _reason(signals):
    labels = {
        "attendance": "участились пропуски",
        "subscription": "заканчивается или истёк абонемент",
        "debt": "есть задолженность",
        "left": "ребёнок ушёл без причины, исключающей возврат",
    }
    return ", ".join(labels.get(signal, signal) for signal in signals)


def create_from_digest(digest, item, task_type, actor, due_at, assignee_id=None):
    data = preview(digest, item, task_type, actor)
    users = {str(user.id): user for user in _admin_users(digest.organization)}
    override = users.get(str(assignee_id)) if assignee_id else None
    if assignee_id and override is None:
        raise DigestTaskError("Исполнитель не найден.")
    children = {
        str(child.id): child
        for child in Child.objects.for_tenant(digest.organization).filter(
            id__in=[row["child_id"] for row in data["items"] if row["child_id"]]
        )
    }
    branches = {
        str(branch.id): branch
        for branch in Branch.objects.for_tenant(digest.organization).filter(
            id__in=[row["branch_id"] for row in data["items"] if row["branch_id"]]
        )
    }
    created = 0
    for row in data["items"]:
        if row["already_exists"]:
            continue
        assignee = override or users[row["assignee_id"]]
        child = children.get(row["child_id"])
        subject = (
            f"Вернуть клиента: {child.full_name}"
            if task_type == Task.Type.RETENTION and child
            else f"Предложить продление: {child.full_name}"
            if task_type == Task.Type.RENEWAL_OFFER and child
            else item.get("title", "Задача из дайджеста")
        )
        reason = (row["reason"] or item.get("rationale", "")).strip()
        action = item.get("action", "").strip()
        description_lines = [f"Из дайджеста за неделю с {digest.week_start:%d.%m.%Y}."]
        # Некоторые шаблоны возвращают одно и то же предложение как основание
        # и действие. В задаче такой дубль не помогает сотруднику.
        if reason and reason != action:
            description_lines.append(f"Основание: {reason}.")
        if action:
            description_lines.append(f"Рекомендация: {action}.")
        description_lines.append(f"Открыть дайджест: /digest?id={digest.id}")
        task = create_task(
            type=task_type,
            assignee=assignee,
            due_date=due_at,
            subject=subject,
            organization=digest.organization,
            source=Task.Source.MANUAL,
            branch=branches.get(row["branch_id"]),
            child=child,
            created_by=actor,
            description="\n".join(description_lines),
            source_key=_source_key(item["id"], task_type, row["child_id"]),
        )
        created += int(task is not None)
    return {"created": created, "skipped": len(data["items"]) - created}
