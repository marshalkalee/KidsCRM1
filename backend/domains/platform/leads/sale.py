"""Закрытие заявки фактической продажей абонемента (TRU-103)."""

import datetime

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from domains.money.subscriptions.models import SubscriptionType
from domains.money.subscriptions.sales import sell_subscription
from domains.scheduling.groups.models import Group, GroupMembership

from .models import Lead
from .services import LeadTransitionError, change_status


class LeadSaleError(ValueError):
    pass


def _sale_child(lead):
    return lead.converted_child or lead.child


def _selectable_types(lead):
    if lead.direction_id is None:
        return SubscriptionType.objects.none()
    qs = SubscriptionType.objects.for_tenant(lead.organization).filter(is_active=True)
    qs = qs.filter(Q(directions=lead.direction) | Q(directions__isnull=True))
    if lead.branch_id:
        qs = qs.filter(Q(branches=lead.branch) | Q(branches__isnull=True))
    return qs.distinct().prefetch_related("versions").order_by("name")


def _suitable_groups(lead, child):
    if lead.direction_id is None:
        return Group.objects.none()
    qs = (
        Group.objects.for_tenant(lead.organization)
        .filter(status=Group.Status.ACTIVE, direction=lead.direction)
        .select_related("branch", "direction")
        .annotate(
            members_count=Count(
                "memberships",
                filter=Q(
                    memberships__left_at__isnull=True,
                    memberships__deleted_at__isnull=True,
                ),
                distinct=True,
            )
        )
    )
    if lead.branch_id:
        qs = qs.filter(branch=lead.branch)
    result = []
    for group in qs.order_by("name"):
        already_member = (
            GroupMembership.objects.for_tenant(lead.organization)
            .filter(group=group, child=child, left_at__isnull=True)
            .exists()
        )
        age_fits = (group.age_min is None or child.age >= group.age_min) and (
            group.age_max is None or child.age <= group.age_max
        )
        if age_fits and (already_member or group.members_count < group.capacity):
            group.already_member = already_member
            result.append(group)
    return result


def sale_options(lead):
    child = _sale_child(lead)
    types = []
    for item in _selectable_types(lead):
        version = item.versions.latest()
        types.append(
            {
                "id": str(item.id),
                "name": version.name,
                "price": str(version.price),
                "is_unlimited": version.is_unlimited,
                "quota_sessions": version.quota_sessions,
                "duration_days": version.duration_days,
            }
        )
    groups = []
    if child is not None:
        groups = [
            {
                "id": str(group.id),
                "name": group.name,
                "branch_name": group.branch.name,
                "members_count": group.members_count,
                "capacity": group.capacity,
                "spots_left": max(0, group.capacity - group.members_count),
                "already_member": group.already_member,
            }
            for group in _suitable_groups(lead, child)
        ]
    return {
        "needs_conversion": child is None,
        "child": child and {"id": str(child.id), "full_name": child.full_name},
        "direction": lead.direction_id
        and {"id": str(lead.direction_id), "name": lead.direction.name},
        "branch": lead.branch_id and {"id": str(lead.branch_id), "name": lead.branch.name},
        "types": types,
        "groups": groups,
        "sold": bool(lead.sold_subscription_id),
    }


def _get_type(lead, subscription_type_id):
    item = _selectable_types(lead).filter(pk=subscription_type_id).first()
    if item is None:
        raise LeadSaleError("Этот тип абонемента недоступен для заявки.")
    return item, item.versions.latest()


def _get_group(lead, child, group_id):
    if not group_id:
        return None, None
    # Блокируем выбранную группу до создания membership: две продажи в
    # последнее свободное место не должны обе пройти проверку вместимости.
    group = (
        Group.objects.for_tenant(lead.organization)
        .select_for_update()
        .select_related("branch", "direction")
        .filter(
            pk=group_id,
            status=Group.Status.ACTIVE,
            direction=lead.direction,
        )
        .first()
    )
    if group is not None and lead.branch_id and group.branch_id != lead.branch_id:
        group = None
    if group is not None and not (
        (group.age_min is None or child.age >= group.age_min)
        and (group.age_max is None or child.age <= group.age_max)
    ):
        group = None
    if group is None:
        raise LeadSaleError("Группа не подходит ребёнку или в ней нет свободных мест.")
    membership = (
        GroupMembership.objects.for_tenant(lead.organization)
        .filter(group=group, child=child, left_at__isnull=True)
        .first()
    )
    occupied = (
        GroupMembership.objects.for_tenant(lead.organization)
        .filter(group=group, left_at__isnull=True)
        .count()
    )
    if membership is None and occupied >= group.capacity:
        raise LeadSaleError("Группа не подходит ребёнку или в ней нет свободных мест.")
    return group, membership


@transaction.atomic
def sell_from_lead(lead, *, actor, data):
    lead = Lead.objects.select_for_update().get(pk=lead.pk, organization=lead.organization)
    if lead.sold_subscription_id:
        return lead, None, False

    child = _sale_child(lead)
    if child is None:
        raise LeadSaleError("Сначала оформите карточку ребёнка и родителя.")
    if lead.direction_id is None:
        raise LeadSaleError("Укажите направление в заявке.")
    already_purchased = lead.status == Lead.Status.PURCHASED
    if not already_purchased and not lead.can_move_to(Lead.Status.PURCHASED):
        raise LeadSaleError("Из текущего статуса нельзя закрыть заявку покупкой.")

    _type, version = _get_type(lead, data["subscription_type"])
    discount = data["discount_amount"]
    price = version.price - discount
    if discount < 0 or discount >= version.price:
        raise LeadSaleError("Скидка должна быть меньше стоимости абонемента.")
    if data["paid_amount"] < 0 or data["paid_amount"] > price:
        raise LeadSaleError("Оплата не может превышать итоговую стоимость.")

    group, membership = _get_group(lead, child, data.get("group"))
    starts_on = data["starts_on"]
    ends_on = starts_on + datetime.timedelta(days=version.duration_days)
    subscription, _payment = sell_subscription(
        actor=actor,
        child=child,
        subscription_type_version=version,
        direction=lead.direction,
        branch=lead.branch,
        starts_on=starts_on,
        ends_on=ends_on,
        discount_amount=discount,
        discount_reason=data.get("discount_reason", ""),
        discount_comment=data.get("discount_comment", ""),
        paid_amount=data["paid_amount"],
        payment_method=data["payment_method"],
        comment=data.get("comment", ""),
    )

    if group is not None and membership is None:
        membership = GroupMembership.objects.create(
            organization=lead.organization,
            group=group,
            child=child,
            joined_at=max(starts_on, timezone.localdate()),
            note="Добавлен при продаже абонемента из заявки.",
        )

    lead.sold_subscription = subscription
    lead.save(update_fields=["sold_subscription", "updated_at"])
    if not already_purchased:
        try:
            lead = change_status(
                lead,
                to_status=Lead.Status.PURCHASED,
                actor=actor,
                comment=f"Продан абонемент «{version.name}».",
            )
        except LeadTransitionError as exc:
            raise LeadSaleError(str(exc)) from exc
    return lead, membership, True
