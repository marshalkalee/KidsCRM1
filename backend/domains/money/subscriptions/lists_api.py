"""
API рабочих списков денег для frontend2: «Задолженности» (TRU-68) и
«Продления» (TRU-69). Цифры — из тех же сервисов, что список детей и
карточка родителя (debt.debtor_subscriptions, renewals.expiring_subscriptions),
не своей арифметикой: экраны сверяют с бухгалтерией центра.

Плательщик, телефон и группа подтягиваются пачкой на страницу, не запросом
на строку. Телефоны — только ролям с can_view_phone.
"""

from datetime import timedelta

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from domains.people.clients.models import ChildContact
from domains.platform.core.active_branch import branch_scope
from domains.platform.core.permissions import CanViewClientMoney, IsNotTeacher
from domains.platform.core.role_permissions import can_view_phone
from domains.platform.core.utils import today_for_org
from domains.platform.leads.models import Lead, LeadKind
from domains.platform.tenants.models import Branch, Direction
from domains.platform.tenants.org_settings import DEBT_OVERDUE_DAYS_THRESHOLD, get_org_setting
from domains.scheduling.groups.models import Group, GroupMembership

from .debt import debtor_subscriptions
from .debt_report import build_debtors_workbook, build_renewals_workbook
from .models import RenewalContact, Subscription
from .renewals import expiring_subscriptions, mark_contacted

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 200
DEBTOR_SORTS = {"debt": "debt", "age": "-starts_on", "child": "child__full_name"}


def _int(params, key, default):
    try:
        return int(params.get(key, default))
    except (TypeError, ValueError):
        return default


def _page(qs, params):
    page = max(1, _int(params, "page", 1))
    size = min(max(1, _int(params, "page_size", DEFAULT_PAGE_SIZE)), MAX_PAGE_SIZE)
    return qs[(page - 1) * size : page * size]


def _branch(request):
    """?branch= — фильтр панели; нет — филиал из шапки (X-Branch-Id), как у списка детей."""
    organization = request.user.organization
    scope = branch_scope(request, request.query_params.get("branch"))
    if scope is not None and len(scope) == 1:
        return Branch.objects.for_tenant(organization).filter(pk=scope[0]).first()
    return None


def _in_scope(request, qs):
    """Несколько своих филиалов («все мои») — фильтр списком."""
    scope = branch_scope(request, request.query_params.get("branch"))
    return qs.filter(branch_id__in=scope) if scope is not None and len(scope) > 1 else qs


def _direction(request):
    direction_id = request.query_params.get("direction")
    if not direction_id:
        return None
    return Direction.objects.for_tenant(request.user.organization).filter(pk=direction_id).first()


def _payers(organization, child_ids):
    """{child_id: ParentContact} — плательщик ребёнка, одним запросом на страницу."""
    links = (
        ChildContact.objects.for_tenant(organization)
        .filter(child_id__in=child_ids, is_payer=True)
        .select_related("parent_contact")
        .prefetch_related("parent_contact__phones")
    )
    return {link.child_id: link.parent_contact for link in links}


def _contact(parent, show_phones):
    if parent is None:
        return {"parent_name": "", "phone": None, "whatsapp": None}
    phones = [p.number for p in parent.phones.all()]
    return {
        "parent_name": parent.full_name,
        "phone": (phones[0] if phones else None) if show_phones else None,
        "whatsapp": (parent.whatsapp or (phones[0] if phones else None)) if show_phones else None,
    }


def _tenge(value) -> str:
    return f"{int(value):,}".replace(",", " ") + " ₸"


# --- Задолженности (TRU-68) --------------------------------------------------


def _debtors_queryset(request):
    organization = request.user.organization
    params = request.query_params
    threshold = get_org_setting(organization, DEBT_OVERDUE_DAYS_THRESHOLD)
    min_age = None
    if params.get("overdue") == "1":
        min_age = threshold
    elif params.get("min_age_days"):
        min_age = max(0, _int(params, "min_age_days", 0))
    qs = debtor_subscriptions(
        organization, branch=_branch(request), direction=_direction(request), min_age_days=min_age
    )
    qs = _in_scope(request, qs)
    query = (params.get("q") or "").strip()
    if query:
        qs = qs.filter(child__full_name__icontains=query)
    return qs, threshold


def debtor_rows(organization, subscriptions, *, show_phones, threshold):
    subscriptions = list(subscriptions)
    today = today_for_org(organization)
    payers = _payers(organization, {s.child_id for s in subscriptions})
    rows = []
    for sub in subscriptions:
        age = (today - sub.starts_on).days
        contact = _contact(payers.get(sub.child_id), show_phones)
        rows.append(
            {
                "subscription_id": str(sub.id),
                "child_id": str(sub.child_id),
                "child_name": sub.child.full_name,
                **contact,
                "subscription_name": sub.subscription_type_version.name,
                "direction_name": sub.direction.name,
                "branch_name": sub.branch.name if sub.branch else "",
                "status": sub.status,
                "starts_on": sub.starts_on.isoformat(),
                "price": str(sub.price),
                "paid": str(sub.paid),
                "debt": str(sub.debt),
                "age_days": age,
                "overdue": age >= threshold,
                "reminder_text": (
                    f"Здравствуйте! Напоминаем об оплате абонемента "
                    f"«{sub.subscription_type_version.name}» ({sub.child.full_name}): "
                    f"к оплате {_tenge(sub.debt)}. Спасибо!"
                ),
            }
        )
    return rows


@api_view(["GET"])
@permission_classes([CanViewClientMoney])
def debtors_api(request):
    """Список долгов по абонементам: фильтры, сортировка, итог по выборке."""
    organization = request.user.organization
    qs, threshold = _debtors_queryset(request)
    total_debt = sum(qs.values_list("debt", flat=True), 0)
    overdue = qs.filter(starts_on__lte=today_for_org(organization) - timedelta(days=threshold))
    sort = request.query_params.get("sort", "debt")
    order = DEBTOR_SORTS.get(sort, "debt")
    if request.query_params.get("dir", "desc") == "desc":
        order = order[1:] if order.startswith("-") else f"-{order}"
    qs = qs.order_by(order, "pk")
    rows = debtor_rows(
        organization,
        _page(qs, request.query_params),
        show_phones=can_view_phone(request.user),
        threshold=threshold,
    )
    return Response(
        {
            "results": rows,
            "count": qs.count(),
            "total_debt": str(total_debt),
            "overdue_count": overdue.count(),
            "overdue_debt": str(sum(overdue.values_list("debt", flat=True), 0)),
            "overdue_days": threshold,
        }
    )


@api_view(["GET"])
@permission_classes([CanViewClientMoney])
def debtors_export_api(request):
    """Та же выборка файлом .xlsx — бухгалтерии для сверки."""
    organization = request.user.organization
    qs, threshold = _debtors_queryset(request)
    show_phones = can_view_phone(request.user)
    rows = debtor_rows(
        organization, qs.order_by("-debt", "pk"), show_phones=show_phones, threshold=threshold
    )
    workbook = build_debtors_workbook(rows, show_phones=show_phones)
    response = HttpResponse(
        workbook.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    name = f"debts-{today_for_org(organization):%Y-%m-%d}.xlsx"
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


# --- Продления (TRU-69) ----------------------------------------------------------

CONTACT_COOLDOWN_DAYS = 7  # «не звонить одному и тому же дважды за неделю» (ТЗ п. 4.4)


def _renewals_queryset(request):
    organization = request.user.organization
    params = request.query_params
    group = None
    if params.get("group"):
        group = Group.objects.for_tenant(organization).filter(pk=params.get("group")).first()
    qs = expiring_subscriptions(
        organization, branch=_branch(request), direction=_direction(request), group=group
    )
    qs = _in_scope(request, qs)
    query = (params.get("q") or "").strip()
    if query:
        qs = qs.filter(child__full_name__icontains=query)
    if params.get("not_contacted") == "1":
        since = today_for_org(organization) - timedelta(days=CONTACT_COOLDOWN_DAYS)
        qs = qs.exclude(renewal_contacts__contacted_at__date__gt=since)
    return qs


def _last_contacts(subscription_ids):
    last = {}
    contacts = (
        RenewalContact.objects.filter(subscription_id__in=subscription_ids)
        .select_related("contacted_by")
        .order_by("subscription_id", "-contacted_at")
    )
    for contact in contacts:
        last.setdefault(contact.subscription_id, contact)
    return last


def _groups(organization, pairs):
    """{(child_id, direction_id): «Группа»} — текущая группа ребёнка по направлению."""
    names = {}
    memberships = (
        GroupMembership.objects.for_tenant(organization)
        .filter(child_id__in={c for c, _ in pairs}, left_at__isnull=True)
        .select_related("group")
        .order_by("joined_at")
    )
    for membership in memberships:
        names.setdefault(
            (membership.child_id, membership.group.direction_id), membership.group.name
        )
    return names


def _open_renewal_leads(organization, child_ids):
    leads = (
        Lead.objects.for_tenant(organization)
        .filter(kind=LeadKind.RENEWAL, child_id__in=child_ids)
        .exclude(status__in=[Lead.Status.PURCHASED, Lead.Status.REJECTED])
        .values_list("child_id", "id")
    )
    return {child_id: str(lead_id) for child_id, lead_id in leads}


def _contact_info(contact, today):
    if contact is None:
        return {"last_contacted_at": None, "last_contacted_by": "", "last_contact_note": ""}
    return {
        "last_contacted_at": contact.contacted_at.isoformat(),
        "last_contacted_by": contact.contacted_by.full_name,
        "last_contact_note": contact.note,
        "contacted_recently": (today - contact.contacted_at.date()).days < CONTACT_COOLDOWN_DAYS,
    }


def renewal_rows(organization, subscriptions, *, show_phones):
    subscriptions = list(subscriptions)
    today = today_for_org(organization)
    child_ids = {s.child_id for s in subscriptions}
    payers = _payers(organization, child_ids)
    groups = _groups(organization, {(s.child_id, s.direction_id) for s in subscriptions})
    contacts = _last_contacts([s.id for s in subscriptions])
    leads = _open_renewal_leads(organization, child_ids)
    rows = []
    for sub in subscriptions:
        days_left = (sub.ends_on - today).days
        remaining = sub.sessions_remaining_cache
        tail = f", осталось занятий: {remaining}" if remaining is not None else ""
        rows.append(
            {
                "subscription_id": str(sub.id),
                "subscription_type_id": str(sub.subscription_type_version.subscription_type_id),
                "child_id": str(sub.child_id),
                "child_name": sub.child.full_name,
                **_contact(payers.get(sub.child_id), show_phones),
                "subscription_name": sub.subscription_type_version.name,
                "direction_name": sub.direction.name,
                "branch_id": str(sub.branch_id) if sub.branch_id else None,
                "branch_name": sub.branch.name if sub.branch else "",
                "group_name": groups.get((sub.child_id, sub.direction_id), ""),
                "sessions_remaining": remaining,
                "ends_on": sub.ends_on.isoformat(),
                "days_left": days_left,
                "contacted_recently": False,
                **_contact_info(contacts.get(sub.id), today),
                "renewal_lead_id": leads.get(sub.child_id),
                "message_text": (
                    f"Здравствуйте! Абонемент «{sub.subscription_type_version.name}» "
                    f"({sub.child.full_name}) заканчивается {sub.ends_on:%d.%m.%Y}{tail}. "
                    f"Продлеваем?"
                ),
            }
        )
    return rows


@api_view(["GET"])
@permission_classes([CanViewClientMoney])
def renewals_api(request):
    """Абонементы «заканчивается» — сначала те, что кончаются раньше."""
    qs = _renewals_queryset(request).order_by("ends_on", "sessions_remaining_cache", "pk")
    rows = renewal_rows(
        request.user.organization,
        _page(qs, request.query_params),
        show_phones=can_view_phone(request.user),
    )
    return Response({"results": rows, "count": qs.count()})


@api_view(["GET"])
@permission_classes([CanViewClientMoney])
def renewals_export_api(request):
    """Та же выборка «Продлений» файлом .xlsx — для сверки (TRU-152)."""
    organization = request.user.organization
    qs = _renewals_queryset(request).order_by("ends_on", "sessions_remaining_cache", "pk")
    show_phones = can_view_phone(request.user)
    rows = renewal_rows(organization, qs, show_phones=show_phones)
    workbook = build_renewals_workbook(rows, show_phones=show_phones)
    response = HttpResponse(
        workbook.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    name = f"renewals-{today_for_org(organization):%Y-%m-%d}.xlsx"
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


@api_view(["POST"])
@permission_classes([IsNotTeacher])
def renewal_contacted_api(request, subscription_id):
    """Отметка «связались» с датой — чтобы не звонить дважды за неделю."""
    organization = request.user.organization
    subscription = get_object_or_404(
        Subscription.objects.for_tenant(organization), pk=subscription_id
    )
    note = str(request.data.get("note", ""))[:255]
    contact = mark_contacted(subscription, actor=request.user, note=note)
    return Response(_contact_info(contact, today_for_org(organization)), status=201)
