"""
ChildService — контракт №2 из TRU-8. Один сервис для поиска дублей и
создания связки ребёнок+родитель, три потребителя: импорт из Excel
(import_service.py), конвертация заявки (M2, домен Bekzat'а — этот файл
и есть согласованный интерфейс) и ручное создание администратором.

Если каждый потребитель считает дубли по-своему, они разойдутся —
поэтому вся логика здесь, а не размазана по вьюхам/сериализаторам.

Правила (порядок = приоритет при дедупе одного и того же ребёнка):
1. Телефон совпал И этот же ребёнок (ФИО+дата рождения) уже привязан к
   найденной семье — почти наверняка та же запись (reason=PHONE).
2. Телефон совпал, но НИ ОДИН ребёнок найденной семьи не совпадает по
   ФИО+дате рождения — это НЕ дубль, это второй ребёнок в семье
   (reason=EXISTING_PARENT_NEW_CHILD, child=None, только parent). Самый
   частый и самый неприятный случай, если не предусмотреть: вместо
   второго ребёнка у одной мамы появятся две мамы с одним номером.
3. ФИО + дата рождения совпали (без привязки к найденному по телефону
   ребёнку выше) — сильное совпадение (reason=NAME_AND_BIRTH_DATE).
4. Только ФИО совпало — слабое совпадение, показать, но не настаивать:
   однофамильцы и тёзки в детском центре — обычное дело
   (reason=NAME_ONLY).

Автоматического слияния нет и не будет — сервис только сообщает, что
нашлось и на каком основании; решение всегда принимает человек.
"""

from dataclasses import dataclass

from django.db import transaction
from django.db.models import Q

from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number

from .models import Child, ChildContact, ContactPhone, ParentContact


class DuplicateReason:
    PHONE = "phone"
    EXISTING_PARENT_NEW_CHILD = "existing_parent_new_child"
    NAME_AND_BIRTH_DATE = "name_and_birth_date"
    NAME_ONLY = "name_only"


@dataclass
class DuplicateMatch:
    reason: str
    # child=None только при EXISTING_PARENT_NEW_CHILD — там речь не про
    # конкретного дублирующегося ребёнка, а про уже существующую семью.
    child: Child | None
    parent: ParentContact | None


def _get_or_create_parent(organization, parent_data):
    """`parent_data` с ключом "id" — существующий ParentContact, иначе —
    новый (с телефонами из "phones")."""
    parent_id = (parent_data or {}).get("id")
    if parent_id:
        return ParentContact.objects.for_tenant(organization).get(pk=parent_id)
    data = dict(parent_data or {})
    phones = data.pop("phones", [])
    parent = ParentContact.objects.create(organization=organization, **data)
    for number in phones:
        ContactPhone.objects.create(organization=organization, parent_contact=parent, number=number)
    return parent


def _primary_contact_parent(organization, child):
    link = (
        ChildContact.objects.for_tenant(organization)
        .filter(child=child)
        .select_related("parent_contact")
        .order_by("-is_primary_contact", "role")
        .first()
    )
    return link.parent_contact if link else None


class ChildService:
    @staticmethod
    def find_duplicates(organization, *, phone=None, child_name=None, birth_date=None):
        """
        Ничего не считается совпадением "любой ценой" — каждый матч несёт
        `reason`, по которому администратор сам решает, дубль это или
        нет (см. докстринг модуля). Невалидный/неполный `phone` (обычное
        дело в Excel-строках) молча пропускается, а не роняет вызов —
        валидация конкретной строки импорта — забота import_service.py,
        не этого сервиса.
        """
        matches = []
        matched_child_ids = set()

        matched_parents = []
        if phone:
            try:
                normalized = normalize_phone_number(phone)
            except InvalidPhoneNumberError:
                normalized = None
            if normalized:
                matched_parents = list(
                    ParentContact.objects.for_tenant(organization)
                    .filter(Q(phones__number=normalized) | Q(whatsapp=normalized))
                    .distinct()
                )

        if matched_parents:
            family_child_ids = set(
                ChildContact.objects.for_tenant(organization)
                .filter(parent_contact__in=matched_parents)
                .values_list("child_id", flat=True)
            )
            family_children = list(
                Child.objects.for_tenant(organization).filter(id__in=family_child_ids)
            )
            same_child_found = False
            for child in family_children:
                if (
                    child_name
                    and birth_date
                    and child.full_name.lower() == child_name.lower()
                    and child.birth_date == birth_date
                ):
                    matches.append(
                        DuplicateMatch(
                            reason=DuplicateReason.PHONE, child=child, parent=matched_parents[0]
                        )
                    )
                    matched_child_ids.add(child.id)
                    same_child_found = True
            if not same_child_found:
                # Тот же телефон, но не тот же ребёнок — второй ребёнок в
                # семье, не дубль (см. докстринг модуля, пункт 2).
                for parent in matched_parents:
                    matches.append(
                        DuplicateMatch(
                            reason=DuplicateReason.EXISTING_PARENT_NEW_CHILD,
                            child=None,
                            parent=parent,
                        )
                    )

        if child_name and birth_date:
            for child in Child.objects.for_tenant(organization).filter(
                full_name__iexact=child_name, birth_date=birth_date
            ):
                if child.id not in matched_child_ids:
                    matches.append(
                        DuplicateMatch(
                            reason=DuplicateReason.NAME_AND_BIRTH_DATE,
                            child=child,
                            parent=_primary_contact_parent(organization, child),
                        )
                    )
                    matched_child_ids.add(child.id)

        if child_name:
            for child in Child.objects.for_tenant(organization).filter(
                full_name__iexact=child_name
            ):
                if child.id not in matched_child_ids:
                    matches.append(
                        DuplicateMatch(
                            reason=DuplicateReason.NAME_ONLY,
                            child=child,
                            parent=_primary_contact_parent(organization, child),
                        )
                    )
                    matched_child_ids.add(child.id)

        return matches

    @staticmethod
    @transaction.atomic
    def create_with_parent(organization, *, child_data, parent_data, link_role):
        """
        Один атомарный вызов на три сущности (Child, опционально новый
        ParentContact+ContactPhone, ChildContact) — частичное создание
        (например, ребёнок без связи) недопустимо.

        `parent_data` с ключом "id" — привязать к УЖЕ существующему
        ParentContact (ровно тот путь, которым второй ребёнок в семье
        должен попадать в систему, см. find_duplicates,
        EXISTING_PARENT_NEW_CHILD), а не тем же способом, что заводит нового
        родителя. Без этого разделения два ребёнка одной мамы дают двух
        разных мам с одинаковым номером — то, что этот тикет должен
        предотвратить.
        """
        child = Child.objects.create(organization=organization, **child_data)
        parent = _get_or_create_parent(organization, parent_data)

        ChildContact.objects.create(
            organization=organization,
            child=child,
            parent_contact=parent,
            role=link_role,
            is_primary_contact=True,
            is_payer=True,
        )
        return child

    @staticmethod
    @transaction.atomic
    def link_parent(organization, child, *, parent_data, link_role):
        """
        Добавить контакт к УЖЕ существующему ребёнку (импорт: администратор
        решил, что строка файла — тот же ребёнок, что уже есть в базе).
        Связь — не основной контакт и не плательщик: существующие связи
        ребёнка не трогаются (иначе ChildContact.save() снял бы флаги с
        уже заведённого плательщика). Если этот родитель уже привязан —
        ничего не создаёт и возвращает существующую связь.

        Возвращает (связь, родитель, создана_ли_связь).
        """
        parent = _get_or_create_parent(organization, parent_data)
        existing = (
            ChildContact.objects.for_tenant(organization)
            .filter(child=child, parent_contact=parent)
            .first()
        )
        if existing:
            return existing, parent, False
        link = ChildContact.objects.create(
            organization=organization,
            child=child,
            parent_contact=parent,
            role=link_role,
            is_primary_contact=False,
            is_payer=False,
        )
        return link, parent, True
