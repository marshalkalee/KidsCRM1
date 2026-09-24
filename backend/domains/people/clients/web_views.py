"""
Веб-страницы карточки ребёнка (серверный рендеринг, сессия) — не DRF
(views.py, JWT). Тот же принцип разделения, что у tenants/web_views.py.

Карточка (child_card) — каркас: шапка + вкладки (ТЗ п. 4.1). Свои две
вкладки («Контакты», «Коммуникации») рендерятся здесь как фрагменты —
тот же фрагмент, что отдаёт AJAX-эндпоинт вкладки, чтобы не поддерживать
два разных шаблона одного и того же содержимого. Остальные три вкладки —
заглушки, см. child_card_tabs.py (контракт для Дарьи/Bekzat'а).
"""

import re
import uuid
from decimal import Decimal
from pathlib import Path

import pytz
from django.contrib import messages
from django.core.files.storage import default_storage
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone as dj_timezone
from django.views.decorators.http import require_http_methods

from domains.money.payments.models import Payment
from domains.money.subscriptions.debt import debt_by_child, debtor_child_ids
from domains.money.subscriptions.models import Subscription
from domains.money.subscriptions.renewals import expiring_child_ids
from domains.platform.core.decorators import role_required
from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number
from domains.platform.core.role_permissions import can_view_client_money, can_view_phone
from domains.platform.tenants.models import Branch, Direction
from domains.scheduling.groups.models import Group, GroupMembership

from .child_card_tabs import get_child_card_tabs
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


def _direction_names(child):
    names = {direction.name for direction in child.directions.all()}
    return ", ".join(sorted(names)) if names else None


CHILD_SORT_FIELDS = {
    "full_name": "full_name",
    "age": "birth_date",
    "status": "status",
}


def _sort_child_queryset(qs, sort, direction):
    # Только скалярные поля Child — филиал/направление/группа/абонемент/
    # долг многозначны (M2M/через другую таблицу) или требуют коррелирующих
    # подзапросов, сортировка по ним сюда не входит в этой задаче (JS-колонки
    # с этими ключами не помечены sortable, см. child_list.html).
    field = CHILD_SORT_FIELDS.get(sort, "full_name")
    descending = direction == "desc"
    if sort == "age":
        # Возраст не хранится (Child.age — вычисляемое свойство, не
        # колонка БД) — сортируем по birth_date, направление обратное:
        # старше = раньше родился, т.е. "возраст по убыванию" — это
        # "дата рождения по возрастанию".
        descending = not descending
    ordering = f"-{field}" if descending else field
    # pk — стабильный tie-break: без него строки с одинаковым значением
    # сортируемого поля могут менять порядок между запросами соседних
    # страниц (LIMIT/OFFSET без полного порядка не гарантирует стабильность).
    return qs.order_by(ordering, "pk")


def _filter_child_queryset(qs, organization, params):
    """Шесть фильтров ТЗ п. 4.1, комбинируются между собой (AND). Долг/
    абонемент — через domains.money.subscriptions (debtor_child_ids/
    expiring_child_ids), не своей копией арифметики: иначе этот список и
    будущие экраны Bekzat'а («Задолженности»/«Продления») разойдутся."""
    needs_distinct = False

    branch_id = params.get("branch")
    if branch_id:
        qs = qs.filter(directions__branches__id=branch_id)
        needs_distinct = True

    direction_id = params.get("direction")
    if direction_id:
        qs = qs.filter(directions__id=direction_id)
        needs_distinct = True

    group_id = params.get("group")
    if group_id:
        qs = qs.filter(
            group_memberships__group_id=group_id, group_memberships__left_at__isnull=True
        )
        needs_distinct = True

    status = params.get("status")
    if status in Child.Status.values:
        qs = qs.filter(status=status)

    if params.get("has_debt") == "1":
        qs = qs.filter(id__in=debtor_child_ids(organization))

    if params.get("expiring") == "1":
        qs = qs.filter(id__in=expiring_child_ids(organization))

    return qs.distinct() if needs_distinct else qs


def _batch_child_extras(organization, child_ids):
    """Группа/абонемент/долг для страницы детей — батчем на весь список
    child_ids, не запросом на каждую строку (ТЗ п. 10.2: иначе 50 строк на
    странице превращаются в 100+ запросов, и бюджет ≤1с не выдерживается)."""
    memberships = (
        GroupMembership.objects.for_tenant(organization)
        .filter(child_id__in=child_ids, left_at__isnull=True)
        .select_related("group")
    )
    groups_by_child = {}
    for membership in memberships:
        groups_by_child.setdefault(membership.child_id, []).append(membership.group.name)

    subscriptions = (
        Subscription.objects.for_tenant(organization)
        .filter(child_id__in=child_ids)
        .select_related("subscription_type_version")
        .order_by("child_id", "-starts_on")
    )
    # Отсортированы по (child_id, -starts_on) — первое вхождение на child_id
    # — самый свежий абонемент, без лишнего запроса с MAX(starts_on)/DISTINCT.
    latest_subscription_by_child = {}
    for sub in subscriptions:
        latest_subscription_by_child.setdefault(sub.child_id, sub)

    # Сумма долга — сервисом домена «Деньги», не своим подсчётом: та же
    # цифра в карточке родителя и на экране задолженностей.
    return groups_by_child, latest_subscription_by_child, debt_by_child(organization, child_ids)


GLOBAL_SEARCH_MIN_LENGTH = 3  # ТЗ п. 4.1: 3 символа имени — уже 4 цифры телефона тоже проходят
GLOBAL_SEARCH_LIMIT_PER_TYPE = 8  # шапка — быстрый список, не полноценная страница результатов


def _phone_digits_and_normalized(raw_query):
    """
    digits — для частичного совпадения (последние 4 цифры и т.п., ТЗ
    п. 4.1); normalized — для точного совпадения по нормализованному
    номеру, когда запрос сам похож на полный номер (тогда "8 701..." и
    "+7 701..." находят один и тот же ContactPhone.number, который всегда
    хранится нормализованным — см. ContactPhone.save()). Без normalized
    один digits__icontains не поймал бы "8" вместо "+7": это не подстрока
    друг друга, хотя номер тот же.
    """
    digits = re.sub(r"\D", "", raw_query or "")
    try:
        normalized = normalize_phone_number(raw_query)
    except InvalidPhoneNumberError:
        normalized = None
    return digits, normalized


def _phone_field_matches(value, phone_digits, phone_normalized):
    if not value:
        return False
    if phone_normalized and value == phone_normalized:
        return True
    return bool(phone_digits) and phone_digits in re.sub(r"\D", "", value)


def _find_matched_phone(parent, phone_digits, phone_normalized):
    """
    Что из телефонов родителя реально совпало с запросом — не "просто
    показать whatsapp, если он есть" (это давало неверный matched_detail:
    родитель мог совпасть по ContactPhone.number, а в подсказке всё равно
    показывался бы его несовпавший whatsapp).
    """
    if _phone_field_matches(parent.whatsapp, phone_digits, phone_normalized):
        return parent.whatsapp
    phone_match = next(
        (
            p
            for p in parent.phones.all()
            if _phone_field_matches(p.number, phone_digits, phone_normalized)
        ),
        None,
    )
    return phone_match.number if phone_match else None


def _global_search_children(organization, query, phone_digits, phone_normalized):
    filters = Q(full_name__icontains=query) | Q(
        contacts__parent_contact__full_name__icontains=query
    )
    if phone_digits:
        filters |= Q(contacts__parent_contact__phones__number__icontains=phone_digits)
        filters |= Q(contacts__parent_contact__whatsapp__icontains=phone_digits)
    if phone_normalized:
        filters |= Q(contacts__parent_contact__phones__number=phone_normalized)
        filters |= Q(contacts__parent_contact__whatsapp=phone_normalized)

    children = (
        Child.objects.for_tenant(organization)
        .filter(filters)
        .distinct()
        .order_by("full_name")
        .prefetch_related("contacts__parent_contact__phones")[:GLOBAL_SEARCH_LIMIT_PER_TYPE]
    )

    query_lower = query.lower()
    results = []
    for child in children:
        matched_on, matched_detail = "child_name", None
        if query_lower not in child.full_name.lower():
            for link in child.contacts.all():
                parent = link.parent_contact
                if query_lower in parent.full_name.lower():
                    matched_on, matched_detail = "parent_name", parent.full_name
                    break
                matched_phone = _find_matched_phone(parent, phone_digits, phone_normalized)
                if matched_phone:
                    matched_on, matched_detail = "phone", matched_phone
                    break
        results.append(
            {
                "type": "child",
                "id": str(child.id),
                "title": child.full_name,
                "matched_on": matched_on,
                "matched_detail": matched_detail,
                "url": reverse("clients_web:child-card", args=[child.pk]),
            }
        )
    return results


def _global_search_parents(organization, query, phone_digits, phone_normalized):
    filters = Q(full_name__icontains=query)
    if phone_digits:
        filters |= Q(whatsapp__icontains=phone_digits) | Q(phones__number__icontains=phone_digits)
    if phone_normalized:
        filters |= Q(whatsapp=phone_normalized) | Q(phones__number=phone_normalized)

    # Родитель — своя строка всегда, даже если у него есть дети: иначе
    # через поиск нельзя попасть в его собственную карточку (контакты,
    # коммуникации, WhatsApp), только в карточки детей. "Один номер в
    # разных написаниях — один результат" (ТЗ п. 4.1) — про стабильность
    # написания номера, а не про то, что родитель и его ребёнок должны
    # схлопнуться в одну строку; бейджи "Родитель"/"Ребёнок" в выдаче
    # различают их и так.
    parents = (
        ParentContact.objects.for_tenant(organization)
        .filter(filters)
        .distinct()
        .order_by("full_name")
        .prefetch_related("phones")[:GLOBAL_SEARCH_LIMIT_PER_TYPE]
    )

    query_lower = query.lower()
    results = []
    for parent in parents:
        if query_lower in parent.full_name.lower():
            matched_on, matched_detail = "parent_name", None
        else:
            matched_on = "phone"
            matched_detail = _find_matched_phone(parent, phone_digits, phone_normalized)
        results.append(
            {
                "type": "parent",
                "id": str(parent.id),
                "title": parent.full_name,
                "matched_on": matched_on,
                "matched_detail": matched_detail,
                "url": reverse("clients_web:parent-card", args=[parent.pk]),
            }
        )
    return results


@role_required()
def global_search(request):
    query = (request.GET.get("q") or "").strip()
    if len(query) < GLOBAL_SEARCH_MIN_LENGTH:
        return JsonResponse({"results": []})

    organization = request.user.organization
    phone_digits, phone_normalized = (
        _phone_digits_and_normalized(query) if can_view_phone(request.user) else (None, None)
    )

    results = _global_search_children(organization, query, phone_digits, phone_normalized)
    results += _global_search_parents(organization, query, phone_digits, phone_normalized)
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
    organization = request.user.organization
    show_money = can_view_client_money(request.user)
    params = request.GET
    if not show_money:
        # Фильтр по долгу — тоже раскрытие денег, пусть и без суммы.
        params = params.copy()
        params.pop("has_debt", None)
        params.pop("expiring", None)
    qs = Child.objects.for_tenant(organization).prefetch_related("directions__branches")
    qs = _filter_child_queryset(qs, organization, params)
    qs = _sort_child_queryset(
        qs, request.GET.get("sort", "full_name"), request.GET.get("dir", "asc")
    )

    try:
        page = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page = 1
    try:
        # Верхняя граница — не даёт с фронта произвольным page_size вернуться
        # к "отдать всё разом" тем же способом, который этот тикет убирает.
        page_size = min(max(1, int(request.GET.get("page_size", 50))), 200)
    except ValueError:
        page_size = 50

    total = qs.count()
    start = (page - 1) * page_size
    children = list(qs[start : start + page_size])

    child_ids = [child.id for child in children]
    groups_by_child, subscription_by_child, debts = _batch_child_extras(organization, child_ids)

    rows = [
        {
            "id": str(child.id),
            "full_name": child.full_name,
            "age": child.age,
            "branch_names": _branch_names(child) or "—",
            "direction_names": _direction_names(child) or "—",
            "group_names": ", ".join(groups_by_child.get(child.id, [])) or "—",
            "status": child.status,
            "subscription_name": (
                subscription_by_child[child.id].subscription_type_version.name
                if show_money and child.id in subscription_by_child
                else None
            ),
            "debt": str(debts.get(child.id, Decimal(0))) if show_money else None,
            "card_url": reverse("clients_web:child-card", args=[child.pk]),
        }
        for child in children
    ]
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
            "branch_names": _branch_names(link.child) or "—",
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


# Сколько последних оплат показать в карточке родителя.
PARENT_PAYMENTS_LIMIT = 50


def _parent_money(organization, parent):
    """Сводно по всем детям родителя (ТЗ п. 4.1): суммарный долг — сервисом
    домена «Деньги» (debt_by_child — та же цифра, что в списке детей), и
    последние оплаты по абонементам всех его детей."""
    child_ids = list(
        ChildContact.objects.for_tenant(organization)
        .filter(parent_contact=parent)
        .values_list("child_id", flat=True)
    )
    total_debt = sum(debt_by_child(organization, child_ids).values(), Decimal(0))
    payments = (
        Payment.objects.for_tenant(organization)
        .filter(subscription__child_id__in=child_ids)
        .select_related("subscription__child", "subscription__subscription_type_version")
        .order_by("-paid_at")[:PARENT_PAYMENTS_LIMIT]
    )
    return {"total_debt": total_debt, "payments": list(payments)}


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
        _parent_money(request.user.organization, parent)
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
