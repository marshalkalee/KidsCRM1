"""
Веб-страница "Контакты ребёнка" (серверный рендеринг, сессия) — не DRF
(views.py, JWT). Тот же принцип разделения, что у tenants/web_views.py.

Минимум по объёму: карточки ребёнка как отдельного экрана ещё нет (тикет
Child был только API) — здесь только раздел контактов по id ребёнка,
без списка детей и без общей карточки. Точка входа — прямая ссылка с id;
навигация к ней — отдельная задача.
"""

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from domains.platform.core.decorators import role_required
from domains.platform.core.role_permissions import can_view_phone

from .forms import ChildContactForm
from .models import Child, ChildContact

OWNER = "owner"
MANAGER = "manager"
ADMIN = "admin"

CHILD_CONTACT_MANAGE_ROLES = (OWNER, MANAGER, ADMIN)


def _is_ajax(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


@role_required()
def child_contacts_list(request, child_id):
    child = get_object_or_404(Child.objects.for_tenant(request.user.organization), pk=child_id)
    links = (
        ChildContact.objects.for_tenant(request.user.organization)
        .filter(child=child)
        .select_related("parent_contact")
        .prefetch_related("parent_contact__phones")
    )
    show_phones = can_view_phone(request.user)

    def _first_phone(link):
        # .all() (не .exists()/.first()) — использует кэш prefetch_related,
        # иначе на каждую строку шёл бы отдельный запрос.
        phones = list(link.parent_contact.phones.all())
        return phones[0].number if phones else None

    rows = [
        {
            "id": str(link.id),
            "full_name": link.parent_contact.full_name,
            "role": link.get_role_display(),
            "is_payer": link.is_payer,
            "is_primary_contact": link.is_primary_contact,
            "phone": _first_phone(link) if show_phones else None,
            "edit_url": reverse("clients_web:child-contact-edit", args=[child.pk, link.pk]),
            "detach_url": reverse("clients_web:child-contact-detach", args=[child.pk, link.pk]),
        }
        for link in links
    ]
    return render(
        request,
        "clients/child_contacts.html",
        {
            "child": child,
            "rows": rows,
            "can_manage": request.user.role in CHILD_CONTACT_MANAGE_ROLES,
        },
    )


@role_required(*CHILD_CONTACT_MANAGE_ROLES)
@require_http_methods(["GET", "POST"])
def child_contact_create(request, child_id):
    child = get_object_or_404(Child.objects.for_tenant(request.user.organization), pk=child_id)
    if request.method == "POST":
        form = ChildContactForm(request.POST, child=child, organization=child.organization)
        if form.is_valid():
            form.save()
            messages.success(request, "Контакт привязан.")
            if _is_ajax(request):
                return JsonResponse({"success": True})
            return redirect("clients_web:child-contacts", child_id=child.pk)
        if _is_ajax(request):
            return render(
                request, "clients/_child_contact_form_fields.html", {"form": form}, status=400
            )
    else:
        form = ChildContactForm(child=child, organization=child.organization)
    if _is_ajax(request):
        return render(request, "clients/_child_contact_form_fields.html", {"form": form})
    return render(
        request,
        "clients/child_contact_form.html",
        {"form": form, "child": child, "is_create": True},
    )


@role_required(*CHILD_CONTACT_MANAGE_ROLES)
@require_http_methods(["GET", "POST"])
def child_contact_edit(request, child_id, pk):
    child = get_object_or_404(Child.objects.for_tenant(request.user.organization), pk=child_id)
    link = get_object_or_404(
        ChildContact.objects.for_tenant(request.user.organization), pk=pk, child=child
    )
    if request.method == "POST":
        form = ChildContactForm(request.POST, instance=link, child=child)
        if form.is_valid():
            form.save()
            messages.success(request, "Контакт обновлён.")
            if _is_ajax(request):
                return JsonResponse({"success": True})
            return redirect("clients_web:child-contacts", child_id=child.pk)
        if _is_ajax(request):
            return render(
                request, "clients/_child_contact_form_fields.html", {"form": form}, status=400
            )
    else:
        form = ChildContactForm(instance=link, child=child)
    if _is_ajax(request):
        return render(request, "clients/_child_contact_form_fields.html", {"form": form})
    return render(
        request,
        "clients/child_contact_form.html",
        {"form": form, "child": child, "is_create": False, "link": link},
    )


@role_required(*CHILD_CONTACT_MANAGE_ROLES)
@require_http_methods(["POST"])
def child_contact_detach(request, child_id, pk):
    child = get_object_or_404(Child.objects.for_tenant(request.user.organization), pk=child_id)
    link = get_object_or_404(
        ChildContact.objects.for_tenant(request.user.organization), pk=pk, child=child
    )
    link.delete()  # мягкое удаление связи — Child и ParentContact не трогает
    messages.success(request, "Контакт отвязан.")
    return redirect("clients_web:child-contacts", child_id=child.pk)
