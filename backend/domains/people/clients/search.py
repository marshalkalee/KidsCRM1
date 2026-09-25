"""
Единый поиск по детям, родителям и телефонам (ТЗ п. 4.1, TRU-31) — один
для шапки старого веба (web_views.global_search) и API для frontend2
(api_views, TRU-80): одинаковые правила совпадения и одинаковое «что
нашлось» в обоих интерфейсах.

Результаты — без ссылок: у старого веба и у React разные адреса карточек,
их добавляет вызывающая сторона по type + id.
"""

import re

from django.db.models import Q

from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number

from .models import Child, ParentContact

GLOBAL_SEARCH_MIN_LENGTH = 3  # ТЗ п. 4.1: 3 символа имени — уже 4 цифры телефона тоже проходят
GLOBAL_SEARCH_LIMIT_PER_TYPE = 8  # шапка — быстрый список, не полноценная страница результатов


def phone_digits_and_normalized(raw_query):
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
            }
        )
    return results


def global_search(organization, query, *, can_view_phone):
    """[{type: child|parent, id, title, matched_on, matched_detail}, ...].
    Пустой список, если запрос короче GLOBAL_SEARCH_MIN_LENGTH. Без права
    видеть телефоны поиск по номеру не выполняется вовсе — иначе по
    совпадению можно было бы подобрать чужой номер."""
    query = (query or "").strip()
    if len(query) < GLOBAL_SEARCH_MIN_LENGTH:
        return []
    phone_digits, phone_normalized = (
        phone_digits_and_normalized(query) if can_view_phone else (None, None)
    )
    results = _global_search_children(organization, query, phone_digits, phone_normalized)
    results += _global_search_parents(organization, query, phone_digits, phone_normalized)
    return results
