"""Экран «Продления» (ТЗ п. 4.4) — рабочий список администратора на
каждый день."""

from urllib.parse import quote

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render

from domains.platform.core.decorators import role_required
from domains.platform.core.role_permissions import CLIENT_MONEY_VIEW_ROLES, can_view_phone
from domains.platform.tenants.models import Branch, Direction
from domains.scheduling.groups.models import Group

from .models import Subscription
from .renewals import expiring_subscriptions, mark_contacted, sell_renewal
from .renewals_forms import RenewalSaleForm

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


def _int_param(params, key, default):
    try:
        return int(params.get(key, default))
    except (TypeError, ValueError):
        return default


def _is_ajax(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _filtered_queryset(request):
    org = request.user.organization
    branch = Branch.objects.filter(pk=request.GET.get("branch")).first()
    direction = Direction.objects.filter(pk=request.GET.get("direction")).first()
    group = Group.objects.filter(pk=request.GET.get("group")).first()
    return expiring_subscriptions(org, branch=branch, direction=direction, group=group)


def _renewal_message(subscription):
    text = (
        f"Здравствуйте! Абонемент {subscription.child.full_name} на "
        f"{subscription.subscription_type_version.name} скоро заканчивается "
        f"({subscription.ends_on:%d.%m.%Y}). Продлить?"
    )
    return quote(text)


@role_required(*CLIENT_MONEY_VIEW_ROLES)
def renewals_page(request):
    org = request.user.organization
    return render(
        request,
        "subscriptions/renewals_list.html",
        {
            "branches": Branch.objects.for_tenant(org),
            "directions": Direction.objects.for_tenant(org),
            "groups": Group.objects.for_tenant(org),
        },
    )


@role_required(*CLIENT_MONEY_VIEW_ROLES)
def renewals_data(request):
    qs = _filtered_queryset(request)
    page = max(1, _int_param(request.GET, "page", 1))
    page_size = min(max(1, _int_param(request.GET, "page_size", DEFAULT_PAGE_SIZE)), MAX_PAGE_SIZE)
    total = qs.count()
    start = (page - 1) * page_size
    subs = list(qs[start : start + page_size])

    show_phones = can_view_phone(request.user)
    rows = []
    for sub in subs:
        payer_link = (
            sub.child.contacts.filter(is_payer=True).select_related("parent_contact").first()
        )
        parent = payer_link.parent_contact if payer_link else None
        membership = (
            sub.child.group_memberships.filter(
                group__direction=sub.direction,
                left_at__isnull=True,
            )
            .select_related("group")
            .first()
        )
        last_contact = sub.renewal_contacts.first()
        rows.append(
            {
                "subscription_id": str(sub.id),
                "child_id": str(sub.child.id),
                "child_name": sub.child.full_name,
                "parent_name": parent.full_name if parent else "",
                "call_url": (
                    f"tel:{parent.phones.first().number}"
                    if show_phones and parent and parent.phones.exists()
                    else None
                ),
                "whatsapp_url": (
                    f"https://wa.me/{parent.whatsapp.lstrip('+')}?text={_renewal_message(sub)}"
                    if show_phones and parent and parent.whatsapp
                    else None
                ),
                "sessions_remaining": sub.sessions_remaining_cache,
                "ends_on": sub.ends_on.isoformat(),
                "group_name": membership.group.name if membership else "",
                "last_contacted": last_contact.contacted_at.isoformat() if last_contact else None,
            }
        )
    return JsonResponse({"rows": rows, "total": total})


@role_required(*CLIENT_MONEY_VIEW_ROLES)
def mark_contacted_view(request, subscription_id):
    if request.method != "POST":
        return HttpResponse(status=405)
    sub = get_object_or_404(
        Subscription.objects.for_tenant(request.user.organization), pk=subscription_id
    )
    mark_contacted(sub, actor=request.user, note=request.POST.get("note", ""))
    return JsonResponse({"ok": True})


@role_required(*CLIENT_MONEY_VIEW_ROLES)
def sell_renewal_view(request, subscription_id):
    org = request.user.organization
    old_sub = get_object_or_404(Subscription.objects.for_tenant(org), pk=subscription_id)

    if request.method == "POST":
        form = RenewalSaleForm(request.POST, organization=org, branch=old_sub.branch)
        if form.is_valid():
            sell_renewal(
                old_sub,
                actor=request.user,
                child=old_sub.child,
                subscription_type_version=form.cleaned_data["subscription_type"].versions.latest(),
                direction=old_sub.direction,
                branch=old_sub.branch,
                starts_on=form.cleaned_data["starts_on"],
                ends_on=form.cleaned_data["ends_on"],
                discount_amount=form.cleaned_data["discount_amount"] or 0,
                discount_reason=form.cleaned_data["discount_reason"],
                paid_amount=form.cleaned_data["paid_amount"],
                payment_method=form.cleaned_data["payment_method"],
            )
            return JsonResponse({"ok": True})
    else:
        form = RenewalSaleForm(
            organization=org,
            branch=old_sub.branch,
            initial={
                "subscription_type": old_sub.subscription_type_version.subscription_type_id,
                "starts_on": old_sub.ends_on,
            },
        )

    template = (
        "subscriptions/_renewal_sale_fields.html"
        if _is_ajax(request)
        else "subscriptions/renewal_sale_form.html"
    )
    return render(request, template, {"form": form, "old_subscription": old_sub})
