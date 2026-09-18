"""
Веб-страницы управления организацией/филиалами/залами (серверный
рендеринг, сессия — см. core/decorators.py). Отдельно от views.py
(DRF ViewSet'ы под JWT для /api/v1/) — разные модели авторизации, смешивать
их в одном файле только запутывало бы, какой запрос под какой auth идёт.
"""

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from domains.platform.core.decorators import role_required
from domains.platform.tenants.forms import (
    BranchForm,
    DirectionForm,
    OrganizationSettingsForm,
    RoomForm,
)
from domains.platform.tenants.models import Branch, Direction, Room
from domains.platform.tenants.org_settings import DEFAULT_ORG_SETTINGS

OWNER = "owner"
MANAGER = "manager"
ADMIN = "admin"
TEACHER = "teacher"

BRANCH_MANAGE_ROLES = (OWNER, MANAGER)
# Залы нужны всем, кроме бухгалтера (см. RoomViewSet.IsNotAccountant в views.py) —
# то же правило, повторённое явно для веб-страниц (page-уровня predicate у
# role_required нет, он принимает только список ролей).
ROOM_MANAGE_ROLES = (OWNER, MANAGER, ADMIN, TEACHER)
# Направления — тот же уровень, что и филиалы: справочник, влияющий на
# расписание/абонементы у всей организации, не рядовая операционная правка.
DIRECTION_MANAGE_ROLES = (OWNER, MANAGER)


def _is_ajax(request):
    """
    jQuery ставит этот заголовок сам; для fetch() его добавляет наш JS
    (см. branch_list.html/room_list.html) — по нему отличаем открытие
    формы в модалке от обычного перехода по прямой ссылке (создание/
    редактирование должно выглядеть как в макете — модалка на полупрозрачном
    фоне, а не отдельная страница; см. тикет "дизайн под макет").
    """
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


@role_required(OWNER)
@require_http_methods(["GET", "POST"])
def organization_settings(request):
    organization = request.user.organization
    if request.method == "POST":
        form = OrganizationSettingsForm(request.POST)
        if form.is_valid():
            form.save(organization)
            messages.success(request, "Настройки организации сохранены.")
            return redirect("tenants_web:organization-settings")
    else:
        initial = {
            "name": organization.name,
            "timezone": organization.timezone,
            **{
                key: organization.settings.get(key, default)
                for key, default in DEFAULT_ORG_SETTINGS.items()
            },
        }
        form = OrganizationSettingsForm(initial=initial)
    return render(request, "tenants/organization_settings.html", {"form": form})


@role_required()
def branch_list(request):
    branches = Branch.objects.for_tenant(request.user.organization).order_by("-is_active", "name")
    rows = [
        {
            "id": str(branch.id),
            "name": branch.name,
            "address": branch.address,
            "phone": branch.phone,
            "is_active": branch.is_active,
            "edit_url": reverse("tenants_web:branch-edit", args=[branch.pk]),
            "rooms_url": reverse("tenants_web:room-list", args=[branch.pk]),
            "archive_url": reverse("tenants_web:branch-archive", args=[branch.pk]),
        }
        for branch in branches
    ]
    return render(request, "tenants/branch_list.html", {"branches": branches, "rows": rows})


@role_required(*BRANCH_MANAGE_ROLES)
@require_http_methods(["GET", "POST"])
def branch_create(request):
    if request.method == "POST":
        form = BranchForm(request.POST)
        if form.is_valid():
            branch = form.save(commit=False)
            branch.organization = request.user.organization
            branch.save()
            messages.success(request, "Филиал создан.")
            if _is_ajax(request):
                return JsonResponse({"success": True})
            return redirect("tenants_web:branch-list")
        if _is_ajax(request):
            return render(request, "tenants/_branch_form_fields.html", {"form": form}, status=400)
    else:
        form = BranchForm()
    if _is_ajax(request):
        return render(request, "tenants/_branch_form_fields.html", {"form": form})
    return render(request, "tenants/branch_form.html", {"form": form, "is_create": True})


@role_required(*BRANCH_MANAGE_ROLES)
@require_http_methods(["GET", "POST"])
def branch_edit(request, pk):
    branch = get_object_or_404(Branch.objects.for_tenant(request.user.organization), pk=pk)
    if request.method == "POST":
        form = BranchForm(request.POST, instance=branch)
        if form.is_valid():
            form.save()
            messages.success(request, "Филиал обновлён.")
            if _is_ajax(request):
                return JsonResponse({"success": True})
            return redirect("tenants_web:branch-list")
        if _is_ajax(request):
            return render(request, "tenants/_branch_form_fields.html", {"form": form}, status=400)
    else:
        form = BranchForm(instance=branch)
    if _is_ajax(request):
        return render(request, "tenants/_branch_form_fields.html", {"form": form})
    return render(
        request, "tenants/branch_form.html", {"form": form, "is_create": False, "branch": branch}
    )


@role_required(*BRANCH_MANAGE_ROLES)
@require_http_methods(["POST"])
def branch_archive(request, pk):
    """
    Архивация — is_active=False, не удаление (ТЗ: критерий приёмки).
    Историю (занятия/оплаты) филиал не теряет — Branch.objects.for_tenant()
    его продолжает возвращать, только пропадает из переключателя в шапке
    (см. core/context_processors.py: branches() фильтрует is_active=True).
    """
    branch = get_object_or_404(Branch.objects.for_tenant(request.user.organization), pk=pk)
    branch.is_active = not branch.is_active
    branch.save(update_fields=["is_active", "updated_at"])
    if branch.is_active:
        messages.success(request, "Филиал восстановлен.")
    else:
        messages.success(request, "Филиал архивирован.")
    return redirect("tenants_web:branch-list")


@role_required()
def room_list(request, branch_pk):
    branch = get_object_or_404(Branch.objects.for_tenant(request.user.organization), pk=branch_pk)
    rooms = Room.objects.for_tenant(request.user.organization).filter(branch=branch)
    rows = [
        {
            "id": str(room.id),
            "name": room.name,
            "capacity": room.capacity,
            "edit_url": reverse("tenants_web:room-edit", args=[branch.pk, room.pk]),
            "delete_url": reverse("tenants_web:room-delete", args=[branch.pk, room.pk]),
        }
        for room in rooms
    ]
    return render(
        request, "tenants/room_list.html", {"branch": branch, "rooms": rooms, "rows": rows}
    )


@role_required(*ROOM_MANAGE_ROLES)
@require_http_methods(["GET", "POST"])
def room_create(request, branch_pk):
    branch = get_object_or_404(Branch.objects.for_tenant(request.user.organization), pk=branch_pk)
    if request.method == "POST":
        form = RoomForm(request.POST)
        if form.is_valid():
            room = form.save(commit=False)
            room.branch = branch
            room.save()
            messages.success(request, "Зал создан.")
            if _is_ajax(request):
                return JsonResponse({"success": True})
            return redirect("tenants_web:room-list", branch_pk=branch.pk)
        if _is_ajax(request):
            return render(request, "tenants/_room_form_fields.html", {"form": form}, status=400)
    else:
        form = RoomForm()
    if _is_ajax(request):
        return render(request, "tenants/_room_form_fields.html", {"form": form})
    return render(
        request, "tenants/room_form.html", {"form": form, "branch": branch, "is_create": True}
    )


@role_required(*ROOM_MANAGE_ROLES)
@require_http_methods(["GET", "POST"])
def room_edit(request, branch_pk, pk):
    branch = get_object_or_404(Branch.objects.for_tenant(request.user.organization), pk=branch_pk)
    room = get_object_or_404(
        Room.objects.for_tenant(request.user.organization), pk=pk, branch=branch
    )
    if request.method == "POST":
        form = RoomForm(request.POST, instance=room)
        if form.is_valid():
            form.save()
            messages.success(request, "Зал обновлён.")
            if _is_ajax(request):
                return JsonResponse({"success": True})
            return redirect("tenants_web:room-list", branch_pk=branch.pk)
        if _is_ajax(request):
            return render(request, "tenants/_room_form_fields.html", {"form": form}, status=400)
    else:
        form = RoomForm(instance=room)
    if _is_ajax(request):
        return render(request, "tenants/_room_form_fields.html", {"form": form})
    return render(
        request,
        "tenants/room_form.html",
        {"form": form, "branch": branch, "is_create": False, "room": room},
    )


@role_required(*ROOM_MANAGE_ROLES)
@require_http_methods(["POST"])
def room_delete(request, branch_pk, pk):
    branch = get_object_or_404(Branch.objects.for_tenant(request.user.organization), pk=branch_pk)
    room = get_object_or_404(
        Room.objects.for_tenant(request.user.organization), pk=pk, branch=branch
    )
    room.delete()  # мягкое удаление — TimestampedSoftDeleteModel.delete()
    messages.success(request, "Зал удалён.")
    return redirect("tenants_web:room-list", branch_pk=branch.pk)


@role_required()
def direction_list(request):
    directions = (
        Direction.objects.for_tenant(request.user.organization)
        .prefetch_related("branches")
        .order_by("-is_active", "name")
    )
    rows = [
        {
            "id": str(direction.id),
            "name": direction.name,
            "color": direction.color,
            "age_min": direction.age_min,
            "age_max": direction.age_max,
            "branch_names": ", ".join(b.name for b in direction.branches.all()),
            "is_active": direction.is_active,
            "edit_url": reverse("tenants_web:direction-edit", args=[direction.pk]),
            "archive_url": reverse("tenants_web:direction-archive", args=[direction.pk]),
        }
        for direction in directions
    ]
    return render(request, "tenants/direction_list.html", {"rows": rows})


@role_required(*DIRECTION_MANAGE_ROLES)
@require_http_methods(["GET", "POST"])
def direction_create(request):
    organization = request.user.organization
    if request.method == "POST":
        form = DirectionForm(request.POST, organization=organization)
        if form.is_valid():
            direction = form.save(commit=False)
            direction.organization = organization
            direction.save()
            form.save_m2m()
            messages.success(request, "Направление создано.")
            if _is_ajax(request):
                return JsonResponse({"success": True})
            return redirect("tenants_web:direction-list")
        if _is_ajax(request):
            return render(
                request, "tenants/_direction_form_fields.html", {"form": form}, status=400
            )
    else:
        form = DirectionForm(organization=organization)
    if _is_ajax(request):
        return render(request, "tenants/_direction_form_fields.html", {"form": form})
    return render(request, "tenants/direction_form.html", {"form": form, "is_create": True})


@role_required(*DIRECTION_MANAGE_ROLES)
@require_http_methods(["GET", "POST"])
def direction_edit(request, pk):
    direction = get_object_or_404(Direction.objects.for_tenant(request.user.organization), pk=pk)
    if request.method == "POST":
        form = DirectionForm(request.POST, instance=direction, organization=direction.organization)
        if form.is_valid():
            form.save()
            messages.success(request, "Направление обновлено.")
            if _is_ajax(request):
                return JsonResponse({"success": True})
            return redirect("tenants_web:direction-list")
        if _is_ajax(request):
            return render(
                request, "tenants/_direction_form_fields.html", {"form": form}, status=400
            )
    else:
        form = DirectionForm(instance=direction, organization=direction.organization)
    if _is_ajax(request):
        return render(request, "tenants/_direction_form_fields.html", {"form": form})
    return render(
        request,
        "tenants/direction_form.html",
        {"form": form, "is_create": False, "direction": direction},
    )


@role_required(*DIRECTION_MANAGE_ROLES)
@require_http_methods(["POST"])
def direction_archive(request, pk):
    """
    Архивация — is_active=False, не удаление (та же логика, что у
    branch_archive). get_selectable_directions() (directions.py) фильтрует
    is_active=True — архивированное направление перестаёт предлагаться при
    создании новой группы/абонемента, но уже существующие продолжают на
    него ссылаться (их Direction никуда не делась, просто is_active=False).
    """
    direction = get_object_or_404(Direction.objects.for_tenant(request.user.organization), pk=pk)
    direction.is_active = not direction.is_active
    direction.save(update_fields=["is_active", "updated_at"])
    if direction.is_active:
        messages.success(request, "Направление восстановлено.")
    else:
        messages.success(request, "Направление архивировано.")
    return redirect("tenants_web:direction-list")
