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
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from domains.people.clients.models import ChildContact
from domains.platform.core.active_branch import get_active_branch
from domains.platform.core.permissions import IsNotTeacher
from domains.platform.core.role_permissions import can_view_phone
from domains.platform.core.utils import today_for_org
from domains.platform.tenants.models import Branch, Direction
from domains.platform.tenants.org_settings import DEBT_OVERDUE_DAYS_THRESHOLD, get_org_setting

from .debt import debtor_subscriptions
from .debt_report import build_debtors_workbook

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
    branch_id = request.query_params.get("branch")
    if branch_id:
        return Branch.objects.for_tenant(organization).filter(pk=branch_id).first()
    return get_active_branch(request)


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
@permission_classes([IsNotTeacher])
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
@permission_classes([IsNotTeacher])
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
