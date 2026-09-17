"""
Веб-страницы карточки ребёнка (серверный рендеринг, сессия) — не DRF
(views.py, JWT). Тот же принцип разделения, что у tenants/web_views.py.

Карточка (child_card) — каркас: шапка + вкладки (ТЗ п. 4.1). Свои две
вкладки («Контакты», «Коммуникации») рендерятся здесь как фрагменты —
тот же фрагмент, что отдаёт AJAX-эндпоинт вкладки, чтобы не поддерживать
два разных шаблона одного и того же содержимого. Остальные три вкладки —
заглушки, см. child_card_tabs.py (контракт для Дарьи/Bekzat'а).
"""

import uuid
from pathlib import Path

from django.contrib import messages
from django.core.files.storage import default_storage
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from domains.platform.core.decorators import role_required
from domains.platform.core.role_permissions import can_view_phone

from .child_card_tabs import get_child_card_tabs
from .forms import (
    ChildContactForm,
    ChildForm,
    ChildPhotoUploadForm,
    CommunicationLogForm,
    ContactPhoneFormSet,
    ParentContactForm,
)
from .models import Child, ChildContact, CommunicationLog, ParentContact

OWNER = "owner"
MANAGER = "manager"
ADMIN = "admin"

CHILD_CONTACT_MANAGE_ROLES = (OWNER, MANAGER, ADMIN)
CHILD_EDIT_ROLES = (OWNER, MANAGER, ADMIN)
COMMUNICATION_LOG_MANAGE_ROLES = (OWNER, MANAGER, ADMIN)
PARENT_MANAGE_ROLES = (OWNER, MANAGER, ADMIN)


def _is_ajax(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _branch_names(child):
    # Филиал не хранится на Child напрямую — выводится из филиалов, где
    # доступны направления ребёнка (Direction.branches, M2M). Не идеально
    # для ребёнка без направлений, но не требует новой связи на модели
    # ради одной строчки в шапке.
    branch_names = {
        branch.name for direction in child.directions.all() for branch in direction.branches.all()
    }
    return ", ".join(sorted(branch_names)) if branch_names else None


def _contacts_tab_context(request, child):
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
    return {
        "child": child,
        "rows": rows,
        "can_manage": request.user.role in CHILD_CONTACT_MANAGE_ROLES,
    }


def _communications_tab_context(request, child, form=None):
    logs = (
        CommunicationLog.objects.for_tenant(request.user.organization)
        .filter(child=child)
        .select_related("author", "parent_contact")
    )
    can_manage = request.user.role in COMMUNICATION_LOG_MANAGE_ROLES
    return {
        "child": child,
        "logs": logs,
        "form": form or (CommunicationLogForm(child=child) if can_manage else None),
        "can_manage": can_manage,
    }


@role_required()
def child_list(request):
    children = Child.objects.for_tenant(request.user.organization).prefetch_related(
        "directions__branches"
    )
    rows = [
        {
            "id": str(child.id),
            "full_name": child.full_name,
            "age": child.age,
            "status": child.status,
            "branch_names": _branch_names(child) or "—",
            "card_url": reverse("clients_web:child-card", args=[child.pk]),
        }
        for child in children
    ]
    return render(
        request,
        "clients/child_list.html",
        {"rows": rows, "can_manage": request.user.role in CHILD_EDIT_ROLES},
    )


@role_required(*CHILD_EDIT_ROLES)
@require_http_methods(["GET", "POST"])
def child_create(request):
    organization = request.user.organization
    if request.method == "POST":
        form = ChildForm(request.POST, organization=organization)
        if form.is_valid():
            child = form.save(commit=False)
            child.organization = organization
            child.save()
            form.save_m2m()
            messages.success(request, "Ребёнок добавлен.")
            if _is_ajax(request):
                return JsonResponse({"success": True})
            return redirect("clients_web:child-list")
        if _is_ajax(request):
            return render(request, "clients/_child_form_fields.html", {"form": form}, status=400)
    else:
        form = ChildForm(organization=organization)
    if _is_ajax(request):
        return render(request, "clients/_child_form_fields.html", {"form": form})
    return render(request, "clients/child_form.html", {"form": form, "is_create": True})


@role_required(*CHILD_EDIT_ROLES)
@require_http_methods(["POST"])
def child_photo_upload(request):
    """Заливка файла Dropzone'ом (form-enhance.js) — отдельно от самой
    ChildForm, потому что при создании Child ещё не существует (нет
    child_id, на который можно было бы что-то прикрепить), а фото должно
    заливаться сразу при выборе файла, до отправки всей формы. Возвращает
    URL — форма просто хранит его в скрытом photo_url (см. ChildForm)."""
    form = ChildPhotoUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        return JsonResponse({"success": False, "errors": form.errors}, status=400)

    uploaded = form.cleaned_data["file"]
    extension = Path(uploaded.name).suffix.lower()
    saved_path = default_storage.save(f"children/photos/{uuid.uuid4()}{extension}", uploaded)
    # URLField на Child требует абсолютный URL (со схемой/хостом) — путь
    # относительно MEDIA_URL сам по себе такую проверку не пройдёт.
    url = request.build_absolute_uri(default_storage.url(saved_path))
    return JsonResponse({"success": True, "url": url})


@role_required()
def child_card(request, child_id):
    child = get_object_or_404(Child.objects.for_tenant(request.user.organization), pk=child_id)
    tabs = [
        {
            "slug": tab.slug,
            "label_key": tab.label_key,
            "label_fallback": tab.label_fallback,
            "url": reverse(tab.url_name, args=[child.pk]) if tab.url_name else None,
        }
        for tab in get_child_card_tabs()
    ]
    return render(
        request,
        "clients/child_card.html",
        {
            "child": child,
            "branch_names": _branch_names(child),
            "tabs": tabs,
            "can_edit": request.user.role in CHILD_EDIT_ROLES,
            "edit_url": reverse("clients_web:child-edit", args=[child.pk]),
            # Первая вкладка отрисовывается сразу на сервере — не ждём
            # лишнего фетча ради самого частого случая (открыли карточку,
            # сразу увидели контакты).
            **_contacts_tab_context(request, child),
        },
    )


@role_required(*CHILD_EDIT_ROLES)
@require_http_methods(["GET", "POST"])
def child_edit(request, child_id):
    child = get_object_or_404(Child.objects.for_tenant(request.user.organization), pk=child_id)
    if request.method == "POST":
        form = ChildForm(request.POST, instance=child, organization=child.organization)
        if form.is_valid():
            form.save()
            messages.success(request, "Карточка ребёнка обновлена.")
            if _is_ajax(request):
                return JsonResponse({"success": True})
            return redirect("clients_web:child-card", child_id=child.pk)
        if _is_ajax(request):
            return render(request, "clients/_child_form_fields.html", {"form": form}, status=400)
    else:
        form = ChildForm(instance=child, organization=child.organization)
    if _is_ajax(request):
        return render(request, "clients/_child_form_fields.html", {"form": form})
    return render(request, "clients/child_form.html", {"form": form, "child": child})


@role_required()
def child_tab_contacts(request, child_id):
    child = get_object_or_404(Child.objects.for_tenant(request.user.organization), pk=child_id)
    return render(request, "clients/_tab_contacts.html", _contacts_tab_context(request, child))


@role_required()
def child_tab_communications(request, child_id):
    child = get_object_or_404(Child.objects.for_tenant(request.user.organization), pk=child_id)
    return render(
        request, "clients/_tab_communications.html", _communications_tab_context(request, child)
    )


@role_required(*COMMUNICATION_LOG_MANAGE_ROLES)
@require_http_methods(["POST"])
def child_communication_create(request, child_id):
    child = get_object_or_404(Child.objects.for_tenant(request.user.organization), pk=child_id)
    form = CommunicationLogForm(request.POST, child=child)
    status_code = 200
    if form.is_valid():
        form.save(author=request.user)
        form = None  # пустая форма для следующей записи
    else:
        status_code = 400
    return render(
        request,
        "clients/_tab_communications.html",
        _communications_tab_context(request, child, form=form),
        status=status_code,
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
            return redirect("clients_web:child-card", child_id=child.pk)
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
            return redirect("clients_web:child-card", child_id=child.pk)
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
    return redirect("clients_web:child-card", child_id=child.pk)


@role_required()
def parent_list(request):
    parents = ParentContact.objects.for_tenant(request.user.organization).prefetch_related("phones")
    show_phones = can_view_phone(request.user)
    rows = [
        {
            "id": str(parent.id),
            "full_name": parent.full_name,
            "phones": ", ".join(p.number for p in parent.phones.all()) if show_phones else None,
            "whatsapp": parent.whatsapp if show_phones else None,
            "email": parent.email,
            "edit_url": reverse("clients_web:parent-edit", args=[parent.pk]),
            "delete_url": reverse("clients_web:parent-delete", args=[parent.pk]),
        }
        for parent in parents
    ]
    return render(
        request,
        "clients/parent_list.html",
        {"rows": rows, "can_manage": request.user.role in PARENT_MANAGE_ROLES},
    )


@role_required(*PARENT_MANAGE_ROLES)
@require_http_methods(["GET", "POST"])
def parent_create(request):
    organization = request.user.organization
    if request.method == "POST":
        form = ParentContactForm(request.POST)
        formset = ContactPhoneFormSet(request.POST, instance=form.instance, prefix="phones")
        if form.is_valid() and formset.is_valid():
            form.instance.organization = organization
            form.save()
            formset.save()
            messages.success(request, "Родитель добавлен.")
            if _is_ajax(request):
                return JsonResponse({"success": True})
            return redirect("clients_web:parent-list")
        if _is_ajax(request):
            return render(
                request,
                "clients/_parent_form_fields.html",
                {"form": form, "formset": formset},
                status=400,
            )
    else:
        form = ParentContactForm()
        formset = ContactPhoneFormSet(instance=form.instance, prefix="phones")
    if _is_ajax(request):
        return render(
            request, "clients/_parent_form_fields.html", {"form": form, "formset": formset}
        )
    return render(
        request,
        "clients/parent_form.html",
        {"form": form, "formset": formset, "is_create": True},
    )


@role_required(*PARENT_MANAGE_ROLES)
@require_http_methods(["GET", "POST"])
def parent_edit(request, pk):
    parent = get_object_or_404(ParentContact.objects.for_tenant(request.user.organization), pk=pk)
    if request.method == "POST":
        form = ParentContactForm(request.POST, instance=parent)
        formset = ContactPhoneFormSet(request.POST, instance=parent, prefix="phones")
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, "Родитель обновлён.")
            if _is_ajax(request):
                return JsonResponse({"success": True})
            return redirect("clients_web:parent-list")
        if _is_ajax(request):
            return render(
                request,
                "clients/_parent_form_fields.html",
                {"form": form, "formset": formset},
                status=400,
            )
    else:
        form = ParentContactForm(instance=parent)
        formset = ContactPhoneFormSet(instance=parent, prefix="phones")
    if _is_ajax(request):
        return render(
            request, "clients/_parent_form_fields.html", {"form": form, "formset": formset}
        )
    return render(
        request,
        "clients/parent_form.html",
        {"form": form, "formset": formset, "is_create": False, "parent": parent},
    )


@role_required(*PARENT_MANAGE_ROLES)
@require_http_methods(["POST"])
def parent_delete(request, pk):
    parent = get_object_or_404(ParentContact.objects.for_tenant(request.user.organization), pk=pk)
    parent.delete()
    messages.success(request, "Родитель удалён.")
    return redirect("clients_web:parent-list")
