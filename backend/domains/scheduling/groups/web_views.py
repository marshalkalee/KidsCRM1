"""
Веб-страницы управления группами (серверный рендеринг, сессия).
Отдельно от views.py (DRF ViewSet под JWT для /api/v1/).
"""

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from domains.platform.core.decorators import role_required
from domains.platform.tenants.models import Branch, Direction
from domains.scheduling.groups.forms import GroupForm
from domains.scheduling.groups.models import Group

from . import queries

OWNER = "owner"
MANAGER = "manager"
ADMIN = "admin"
TEACHER = "teacher"

GROUP_MANAGE_ROLES = (OWNER, MANAGER)


def _is_ajax(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


@role_required()
def group_list(request):
    org = request.user.organization
    # Порог — из настроек организации (раньше читался несуществующий ключ
    # "group_fill_threshold" и всегда был 70%).
    threshold = queries.underfilled_threshold(org)

    groups = queries.with_members_count(
        Group.objects.for_tenant(org)
        .select_related("branch", "direction")
        .prefetch_related("teachers")
        .order_by("status", "name")
    )

    # Преподаватель видит только свои группы — как в API.
    if request.user.role == "teacher":
        groups = groups.filter(teachers=request.user)

    # Фильтры
    branch_id = request.GET.get("branch")
    direction_id = request.GET.get("direction")
    status_filter = request.GET.get("status")
    teacher_id = request.GET.get("teacher")

    if branch_id:
        groups = groups.filter(branch_id=branch_id)
    if direction_id:
        groups = groups.filter(direction_id=direction_id)
    if status_filter:
        groups = groups.filter(status=status_filter)
    if teacher_id:
        groups = groups.filter(teachers__id=teacher_id)

    # Для фильтров
    branches = Branch.objects.for_tenant(org).filter(is_active=True).order_by("name")
    directions = Direction.objects.for_tenant(org).filter(is_active=True).order_by("name")

    rows = [
        {
            "id": str(g.id),
            "name": g.name,
            "direction_name": g.direction.name if g.direction else "",
            "direction_color": g.direction.color if g.direction else "#999",
            "branch_name": g.branch.name if g.branch else "",
            "teacher_names": ", ".join(t.get_full_name() or str(t.phone) for t in g.teachers.all()),
            "capacity": g.capacity,
            "members_count": g.members_count,
            "fill_pct": queries.fill_percent(g),
            "is_underfilled": queries.is_underfilled(g, threshold),
            "status": g.status,
            "age_range": f"{g.age_min}–{g.age_max}" if g.age_min and g.age_max else "",
            "detail_url": reverse("scheduling_web:group-detail", args=[g.pk]),
            "edit_url": reverse("scheduling_web:group-edit", args=[g.pk]),
            "close_url": reverse("scheduling_web:group-close", args=[g.pk]),
            "branch_id": str(g.branch.id) if g.branch else "",
            "direction_id": str(g.direction.id) if g.direction else "",
        }
        for g in groups
    ]

    return render(
        request,
        "scheduling/group_list.html",
        {
            "rows": rows,
            "groups": groups,
            "branches": branches,
            "directions": directions,
            "threshold": threshold,
            "current_branch": branch_id,
            "current_direction": direction_id,
            "current_status": status_filter,
        },
    )


@role_required(*GROUP_MANAGE_ROLES)
@require_http_methods(["GET", "POST"])
def group_create(request):
    org = request.user.organization
    if request.method == "POST":
        form = GroupForm(request.POST, organization=org)
        if form.is_valid():
            group = form.save(commit=False)
            group.organization = org
            group.save()
            form.save_m2m()
            messages.success(request, "Группа создана.")
            if _is_ajax(request):
                return JsonResponse({"success": True})
            return redirect("scheduling_web:group-list")
        if _is_ajax(request):
            return render(request, "scheduling/_group_form_fields.html", {"form": form}, status=400)
    else:
        form = GroupForm(organization=org)
    if _is_ajax(request):
        return render(request, "scheduling/_group_form_fields.html", {"form": form})
    return render(request, "scheduling/group_form.html", {"form": form, "is_create": True})


@role_required(*GROUP_MANAGE_ROLES)
@require_http_methods(["GET", "POST"])
def group_edit(request, pk):
    org = request.user.organization
    group = get_object_or_404(Group.objects.for_tenant(org), pk=pk)
    if request.method == "POST":
        form = GroupForm(request.POST, instance=group, organization=org)
        if form.is_valid():
            form.save()
            messages.success(request, "Группа обновлена.")
            if _is_ajax(request):
                return JsonResponse({"success": True})
            return redirect("scheduling_web:group-list")
        if _is_ajax(request):
            return render(request, "scheduling/_group_form_fields.html", {"form": form}, status=400)
    else:
        form = GroupForm(instance=group, organization=org)
    if _is_ajax(request):
        return render(request, "scheduling/_group_form_fields.html", {"form": form})
    return render(
        request,
        "scheduling/group_form.html",
        {"form": form, "is_create": False, "group": group},
    )


@role_required()
def group_detail(request, pk):
    org = request.user.organization
    group = get_object_or_404(
        queries.with_members_count(
            Group.objects.for_tenant(org)
            .select_related("branch", "direction")
            .prefetch_related("teachers", "memberships__child")
        ),
        pk=pk,
    )
    active_memberships = group.memberships.filter(left_at__isnull=True).select_related("child")
    return render(
        request,
        "scheduling/group_detail.html",
        {
            "group": group,
            "active_memberships": active_memberships,
            "fill_pct": queries.fill_percent(group),
        },
    )


@role_required(*GROUP_MANAGE_ROLES)
@require_http_methods(["POST"])
def group_close(request, pk):
    group = get_object_or_404(Group.objects.for_tenant(request.user.organization), pk=pk)
    if group.status == Group.Status.CLOSED:
        group.status = Group.Status.ACTIVE
        messages.success(request, "Группа восстановлена.")
    else:
        group.status = Group.Status.CLOSED
        messages.success(request, "Группа закрыта.")
    group.save(update_fields=["status", "updated_at"])
    return redirect("scheduling_web:group-list")
