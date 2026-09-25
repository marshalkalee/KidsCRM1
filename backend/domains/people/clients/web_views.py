"""
Веб-страницы карточки ребёнка (серверный рендеринг, сессия) — не DRF
(views.py, JWT). Тот же принцип разделения, что у tenants/web_views.py.

Карточка (child_card) — каркас: шапка + вкладки (ТЗ п. 4.1). Свои две
вкладки («Контакты», «Коммуникации») рендерятся здесь как фрагменты —
тот же фрагмент, что отдаёт AJAX-эндпоинт вкладки, чтобы не поддерживать
два разных шаблона одного и того же содержимого. Остальные три вкладки —
заглушки, см. child_card_tabs.py (контракт для Дарьи/Bekzat'а).
"""

import pytz
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone as dj_timezone
from django.views.decorators.http import require_http_methods

from domains.platform.core.decorators import role_required
from domains.platform.core.role_permissions import can_view_client_money, can_view_phone
from domains.platform.tenants.models import Branch, Direction
from domains.scheduling.groups.models import Group

from . import search
from .child_card_tabs import get_child_card_tabs
from .child_list import branch_names, list_children
from .forms import (
    ChildContactForm,
    ChildForm,
    ChildPhotoUploadForm,
    CommunicationLogForm,
    ContactPhoneFormSet,
    ParentCommunicationLogForm,
    ParentContactForm,
)
from .models import Child, ChildContact, CommunicationLog, ParentContact
from .parents import DELETE_BLOCKED_MESSAGE, can_delete_parent, parent_money
from .photos import save_child_photo

OWNER = "owner"
MANAGER = "manager"
ADMIN = "admin"

CHILD_CONTACT_MANAGE_ROLES = (OWNER, MANAGER, ADMIN)
CHILD_EDIT_ROLES = (OWNER, MANAGER, ADMIN)
COMMUNICATION_LOG_MANAGE_ROLES = (OWNER, MANAGER, ADMIN)
PARENT_MANAGE_ROLES = (OWNER, MANAGER, ADMIN)


def _is_ajax(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


_SEARCH_CARD_URLS = {
    "child": "clients_web:child-card",
    "parent": "clients_web:parent-card",
}


@role_required()
def global_search(request):
    results = search.global_search(
        request.user.organization,
        request.GET.get("q"),
        can_view_phone=can_view_phone(request.user),
    )
    for result in results:
        result["url"] = reverse(_SEARCH_CARD_URLS[result["type"]], args=[result["id"]])
    return JsonResponse({"results": results})


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
            # role_code — сырое значение (например "father"), нужно JS
            # (child_card.html) для перевода через choices.child_contact_role.*
            # (i18n.js); role — русский текст как HTML-фолбэк по умолчанию,
            # тот же принцип, что у всех остальных строк на сайте.
            "role": link.get_role_display(),
            "role_code": link.role,
            "is_payer": link.is_payer,
            "is_primary_contact": link.is_primary_contact,
            "phone": _first_phone(link) if show_phones else None,
            "card_url": reverse("clients_web:parent-card", args=[link.parent_contact.pk]),
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


def _serialize_communication_logs(logs, organization):
    # Общий формат строк для communications-feed.js (схлопывание после N
    # записей + фильтр по датам) — используется и на вкладке ребёнка, и на
    # сводной ленте карточки родителя, чтобы не разойтись в двух местах.
    tz_name = getattr(organization, "timezone", None)
    org_tz = pytz.timezone(tz_name) if tz_name else dj_timezone.get_default_timezone()
    rows = []
    for log in logs:
        local_dt = dj_timezone.localtime(log.created_at, org_tz)
        rows.append(
            {
                "id": str(log.id),
                "channel_code": log.channel,
                "channel_display": log.get_channel_display(),
                "note": log.note,
                "author": log.author.full_name,
                "child_name": log.child.full_name,
                "contact_name": log.parent_contact.full_name if log.parent_contact else None,
                "date": local_dt.strftime("%Y-%m-%d"),
                "date_display": local_dt.strftime("%d.%m.%Y %H:%M"),
            }
        )
    return rows


def _communications_tab_context(request, child, form=None):
    logs = (
        CommunicationLog.objects.for_tenant(request.user.organization)
        .filter(child=child)
        .select_related("author", "parent_contact")
    )
    can_manage = request.user.role in COMMUNICATION_LOG_MANAGE_ROLES
    return {
        "child": child,
        "logs": _serialize_communication_logs(logs, request.user.organization),
        "form": form or (CommunicationLogForm(child=child) if can_manage else None),
        "can_manage": can_manage,
    }


@role_required()
def child_list(request):
    # Каркас страницы — сами строки грузит child_list_data() (удалённый
    # режим table.js): на 5000 детей отдавать всё разом одним json_script,
    # как раньше, не укладывается в бюджет ≤1с (ТЗ п. 10.2). Списки для
    # <select> фильтров — реальные справочники организации; сами значения
    # фильтров read/write делает JS из query-строки (см. child_list.html),
    # не эта view — ссылку с фильтрами должно быть можно переслать коллеге.
    organization = request.user.organization
    return render(
        request,
        "clients/child_list.html",
        {
            "can_manage": request.user.role in CHILD_EDIT_ROLES,
            "branches": Branch.objects.for_tenant(organization).filter(is_active=True),
            "directions": Direction.objects.for_tenant(organization),
            "groups": Group.objects.for_tenant(organization),
            "statuses": Child.Status.choices,
        },
    )


@role_required()
def child_list_data(request):
    rows, total = list_children(
        request.user.organization, request.GET, show_money=can_view_client_money(request.user)
    )
    for row in rows:
        row["card_url"] = reverse("clients_web:child-card", args=[row["id"]])
    return JsonResponse({"rows": rows, "total": total})


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

    url = save_child_photo(request, form.cleaned_data["file"])
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
            "branch_names": branch_names(child),
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
            "card_url": reverse("clients_web:parent-card", args=[parent.pk]),
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
    if not can_delete_parent(request.user.organization, parent):
        messages.error(request, DELETE_BLOCKED_MESSAGE)
        return redirect("clients_web:parent-card", pk=parent.pk)
    parent.delete()
    messages.success(request, "Родитель удалён.")
    return redirect("clients_web:parent-list")


def _parent_children_rows(request, parent):
    links = (
        ChildContact.objects.for_tenant(request.user.organization)
        .filter(parent_contact=parent)
        .select_related("child")
        .prefetch_related("child__directions__branches")
    )
    return [
        {
            "id": str(link.child.id),
            "full_name": link.child.full_name,
            "role": link.get_role_display(),
            "role_code": link.role,
            "branch_names": branch_names(link.child) or "—",
            "card_url": reverse("clients_web:child-card", args=[link.child.pk]),
        }
        for link in links
    ]


def _parent_communication_logs(request, parent):
    # По ребёнку, не по CommunicationLog.parent_contact: тот необязателен
    # (звонок не всегда привязан к конкретному контакту, см. docstring
    # модели), а сводная лента родителя — это "всё по любому из его детей",
    # а не только записи, где явно отмечен именно этот контакт.
    child_ids = ChildContact.objects.filter(parent_contact=parent).values_list(
        "child_id", flat=True
    )
    logs = (
        CommunicationLog.objects.for_tenant(request.user.organization)
        .filter(child_id__in=child_ids)
        .select_related("child", "author")
    )
    return _serialize_communication_logs(logs, parent.organization)


@role_required()
def parent_card(request, pk):
    parent = get_object_or_404(ParentContact.objects.for_tenant(request.user.organization), pk=pk)
    show_phones = can_view_phone(request.user)
    can_manage = request.user.role in PARENT_MANAGE_ROLES
    phones = list(parent.phones.all()) if show_phones else []
    # tel:/wa.me — тот же нормализованный "+7..." (см. phone.py), wa.me
    # хочет только цифры без "+" (ТЗ п. 4.5 — deep-link). show_phones — та
    # же проверка, что скрывает сам номер: иначе номер утекал бы через
    # href кнопки WhatsApp тому, кому нельзя видеть его текстом.
    money = (
        parent_money(request.user.organization, parent)
        if can_view_client_money(request.user)
        else None
    )
    call_url = f"tel:{phones[0].number}" if phones else None
    whatsapp_url = (
        f"https://wa.me/{parent.whatsapp.lstrip('+')}" if show_phones and parent.whatsapp else None
    )
    return render(
        request,
        "clients/parent_card.html",
        {
            "parent": parent,
            "children_rows": _parent_children_rows(request, parent),
            "communication_logs": _parent_communication_logs(request, parent),
            "phones": phones if show_phones else None,
            "whatsapp": parent.whatsapp if show_phones else None,
            "call_url": call_url,
            "whatsapp_url": whatsapp_url,
            "can_manage": can_manage,
            "money": money,
            "edit_url": reverse("clients_web:parent-edit", args=[parent.pk]),
            "communication_create_url": reverse(
                "clients_web:parent-communication-create", args=[parent.pk]
            ),
        },
    )


@role_required(*COMMUNICATION_LOG_MANAGE_ROLES)
@require_http_methods(["GET", "POST"])
def parent_communication_create(request, pk):
    parent = get_object_or_404(ParentContact.objects.for_tenant(request.user.organization), pk=pk)
    if request.method == "POST":
        form = ParentCommunicationLogForm(request.POST, parent_contact=parent)
        if form.is_valid():
            form.save(author=request.user)
            messages.success(request, "Коммуникация записана.")
            if _is_ajax(request):
                return JsonResponse({"success": True})
            return redirect("clients_web:parent-card", pk=parent.pk)
        if _is_ajax(request):
            return render(
                request,
                "clients/_parent_communication_form_fields.html",
                {"form": form},
                status=400,
            )
    else:
        form = ParentCommunicationLogForm(parent_contact=parent)
    if _is_ajax(request):
        return render(request, "clients/_parent_communication_form_fields.html", {"form": form})
    return render(
        request,
        "clients/parent_communication_form.html",
        {"form": form, "parent": parent},
    )
