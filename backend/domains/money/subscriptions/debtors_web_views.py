"""Экран «Задолженности» (ТЗ п. 4.4, критерий приёмки MVP №4)."""


from django.http import HttpResponse, JsonResponse
from django.shortcuts import render

from domains.platform.core.decorators import role_required
from domains.platform.core.role_permissions import CLIENT_MONEY_VIEW_ROLES, can_view_phone
from domains.platform.tenants.models import Branch, Direction

from .debt import debt_age_days, debtor_subscriptions
from .debt_report import build_debtors_workbook
from .tasks_stub import create_debt_reminder_task

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
SORT_FIELDS = {"child_name": "child__full_name", "debt": "debt", "age_days": "starts_on"}


def _int_param(params, key, default):
    try:
        return int(params.get(key, default))
    except (TypeError, ValueError):
        return default


def _filtered_queryset(request):
    org = request.user.organization
    branch = Branch.objects.filter(pk=request.GET.get("branch")).first()
    direction = Direction.objects.filter(pk=request.GET.get("direction")).first()
    min_age_days = request.GET.get("min_age_days")
    return debtor_subscriptions(
        org,
        branch=branch,
        direction=direction,
        min_age_days=int(min_age_days) if min_age_days else None,
    )


@role_required(*CLIENT_MONEY_VIEW_ROLES)
def debtors_page(request):
    org = request.user.organization
    return render(
        request,
        "subscriptions/debtors_list.html",
        {
            "branches": Branch.objects.for_tenant(org),
            "directions": Direction.objects.for_tenant(org),
            "show_phones": can_view_phone(request.user),
        },
    )


@role_required(*CLIENT_MONEY_VIEW_ROLES)
def debtors_data(request):
    qs = _filtered_queryset(request)

    total_debt = sum((s.debt for s in qs), 0)

    sort_key = SORT_FIELDS.get(request.GET.get("sort"), "-debt")
    if request.GET.get("dir") == "desc" and not sort_key.startswith("-"):
        sort_key = f"-{sort_key}"
    qs = qs.order_by(sort_key)

    page = max(1, _int_param(request.GET, "page", 1))
    page_size = min(max(1, _int_param(request.GET, "page_size", DEFAULT_PAGE_SIZE)), MAX_PAGE_SIZE)
    total = qs.count()
    start = (page - 1) * page_size
    subs = list(qs[start : start + page_size])

    show_phones = can_view_phone(request.user)
    rows = []
    for sub in subs:
        payer = sub.child.contacts.filter(is_payer=True).select_related("parent_contact").first()
        parent = payer.parent_contact if payer else None
        whatsapp_url = (
            f"https://wa.me/{parent.whatsapp.lstrip('+')}"
            if show_phones and parent and parent.whatsapp
            else None
        )
        rows.append(
            {
                "child_id": str(sub.child.id),
                "child_name": sub.child.full_name,
                "parent_name": parent.full_name if parent else "",
                "call_url": (
                    f"tel:{parent.phones.first().number}"
                    if show_phones and parent and parent.phones.exists()
                    else None
                ),
                "whatsapp_url": whatsapp_url,
                "subscription_name": sub.subscription_type_version.name,
                "debt": str(sub.debt),
                "age_days": debt_age_days(sub),
            }
        )
    return JsonResponse({"rows": rows, "total": total, "total_debt": str(total_debt)})


@role_required(*CLIENT_MONEY_VIEW_ROLES)
def create_reminder_task_view(request, subscription_id):
    if request.method != "POST":
        return HttpResponse(status=405)
    sub = _filtered_queryset(request).filter(pk=subscription_id).first()
    if sub is None:
        return HttpResponse(status=404)
    create_debt_reminder_task(sub.child, sub)
    return JsonResponse({"ok": True})


@role_required(*CLIENT_MONEY_VIEW_ROLES)
def export_debtors(request):
    workbook = build_debtors_workbook(_filtered_queryset(request).order_by("-debt"))
    response = HttpResponse(
        workbook.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="debtors.xlsx"'
    return response
