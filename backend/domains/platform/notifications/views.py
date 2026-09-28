from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from domains.platform.core.active_branch import get_active_branch
from domains.platform.core.permissions import IsStaffOfOrganization
from domains.platform.users.models import User

from .models import NotificationSeen
from .sources import SOURCES


def visible_branch_ids(request):
    """
    Какие филиалы видит сотрудник (ТЗ п. 2): владелец — все или выбранный в
    шапке; остальные — закреплённые за ними (выбор в шапке сужает, но не
    расширяет). None — без ограничения.
    """
    user = request.user
    active = get_active_branch(request)
    own = (
        None
        if user.role == User.Role.OWNER
        else list(user.branches.values_list("id", flat=True)) or None
    )
    if active is not None and (own is None or active.id in own):
        return [active.id]
    return own


def collect(request):
    user = request.user
    branch_ids = visible_branch_ids(request)
    seen = {row.kind: row for row in NotificationSeen.objects.filter(user=user)}
    items = []
    for source in SOURCES:
        item = source(user, branch_ids)
        if item is None:  # не для этой роли
            continue
        mark = seen.get(item.kind)
        if not item.available or item.count == 0:
            unread = False
        elif mark is None:
            unread = True
        elif item.latest_at is not None:
            unread = item.latest_at > mark.seen_at
        else:
            unread = item.count > mark.seen_count
        items.append(
            {
                "kind": item.kind,
                "count": item.count,
                "unread": unread,
                "link": item.link,
                "available": item.available,
                "latest_at": item.latest_at,
                **item.extra,
            }
        )
    return items


@api_view(["GET"])
@permission_classes([IsStaffOfOrganization])
def notifications(request, version=None):
    """Центр уведомлений (TRU-72): по виду — сколько, есть ли новое, куда вести."""
    items = collect(request)
    return Response({"items": items, "unread": sum(1 for item in items if item["unread"])})


@api_view(["POST"])
@permission_classes([IsStaffOfOrganization])
def mark_seen(request, version=None):
    """«Прочитано»: {kind} — один вид, {kind: "all"} — все. Запоминаем время и
    текущее число — новое после этого снова будет непрочитанным."""
    kind = request.data.get("kind")
    items = {item["kind"]: item for item in collect(request)}
    kinds = list(items) if kind == "all" else [kind]
    if not kinds or any(k not in items for k in kinds):
        return Response({"kind": ["Нет такого уведомления."]}, status=status.HTTP_400_BAD_REQUEST)
    now = timezone.now()
    for k in kinds:
        NotificationSeen.objects.update_or_create(
            user=request.user, kind=k, defaults={"seen_at": now, "seen_count": items[k]["count"]}
        )
    items = collect(request)
    return Response({"items": items, "unread": sum(1 for item in items if item["unread"])})
