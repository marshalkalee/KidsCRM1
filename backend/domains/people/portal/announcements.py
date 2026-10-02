"""
Объявления центра (TRU-140): кому видно, лента родителя, охват.

Объявление видит родитель, если хотя бы один его ребёнок в этом центре
ходит (статус «активен», «пробный» или «приостановлен») и подходит под
адресата:
- весь центр — любой такой ребёнок;
- филиал — ребёнок в группе этого филиала;
- направление — ребёнок в группе этого направления или с этим
  направлением в карточке;
- группа — ребёнок сейчас в этой группе.
Ушедшие дети объявлений не получают: концерт для них не актуален.

Активные — опубликованы и не истекли (expires_on — до этой даты
включительно, по дате центра). Истёкшие — в архиве.
"""

from django.db.models import Q
from django.utils import timezone

from domains.people.clients.models import Child
from domains.platform.core.utils import today_for_org
from domains.scheduling.groups.models import GroupMembership

from . import access
from .models import Announcement, AnnouncementRead

ATTENDING = (Child.Status.ACTIVE, Child.Status.TRIAL, Child.Status.PAUSED)


def _child_targets(child):
    memberships = GroupMembership.objects.filter(child=child, left_at__isnull=True).select_related(
        "group"
    )
    groups = {m.group_id for m in memberships}
    branches = {m.group.branch_id for m in memberships if m.group.branch_id}
    directions = {m.group.direction_id for m in memberships if m.group.direction_id}
    directions |= set(child.directions.values_list("id", flat=True))
    return groups, branches, directions


def audience_filter(groups, branches, directions):
    return (
        Q(audience=Announcement.Audience.ORGANIZATION)
        | Q(audience=Announcement.Audience.BRANCH, branch_id__in=branches)
        | Q(audience=Announcement.Audience.DIRECTION, direction_id__in=directions)
        | Q(audience=Announcement.Audience.GROUP, group_id__in=groups)
    )


def published(organization):
    return Announcement.objects.for_tenant(organization).filter(
        status=Announcement.Status.PUBLISHED, published_at__lte=timezone.now()
    )


def feed(account, archive=False):
    """Объявления родителя по всем его центрам. Для каждого — к кому из
    его детей относится и прочитано ли."""
    kids = [c for c in access.children_for_phone(account.phone) if c.status in ATTENDING]
    by_announcement = {}
    for child in kids:
        today = today_for_org(child.organization)
        qs = published(child.organization).filter(audience_filter(*_child_targets(child)))
        if archive:
            qs = qs.filter(expires_on__lt=today)
        else:
            qs = qs.filter(Q(expires_on__isnull=True) | Q(expires_on__gte=today))
        for announcement in qs.select_related("organization"):
            entry = by_announcement.setdefault(
                announcement.pk, {"announcement": announcement, "children": []}
            )
            entry["children"].append(child.full_name)
    read = set(
        AnnouncementRead.objects.filter(
            account=account, announcement_id__in=by_announcement
        ).values_list("announcement_id", flat=True)
    )
    rows = [
        {
            "id": str(a.pk),
            "title": a.title,
            "body": a.body,
            "published_at": a.published_at,
            "expires_on": a.expires_on,
            "organization": a.organization.name,
            "attachment_url": a.attachment_url,
            "attachment_name": a.attachment_name,
            "children": sorted(entry["children"]),
            "read": a.pk in read,
        }
        for entry in by_announcement.values()
        for a in [entry["announcement"]]
    ]
    rows.sort(key=lambda r: r["published_at"], reverse=True)
    return rows


def visible_to(account, announcement_id):
    return any(
        row["id"] == str(announcement_id) for row in feed(account) + feed(account, archive=True)
    )


def mark_read(account, announcement_id):
    AnnouncementRead.objects.get_or_create(account=account, announcement_id=announcement_id)


def reach(announcement):
    """Сколько детей (а значит семей) увидят объявление — для экрана центра."""
    organization = announcement.organization
    kids = Child.objects.for_tenant(organization).filter(status__in=ATTENDING)
    if announcement.audience == Announcement.Audience.ORGANIZATION:
        return kids.count()
    active = Q(group_memberships__left_at__isnull=True)
    if announcement.audience == Announcement.Audience.BRANCH:
        return (
            kids.filter(active, group_memberships__group__branch_id=announcement.branch_id)
            .distinct()
            .count()
        )
    if announcement.audience == Announcement.Audience.GROUP:
        return (
            kids.filter(active, group_memberships__group_id=announcement.group_id)
            .distinct()
            .count()
        )
    return (
        kids.filter(
            Q(active, group_memberships__group__direction_id=announcement.direction_id)
            | Q(directions=announcement.direction_id)
        )
        .distinct()
        .count()
    )
