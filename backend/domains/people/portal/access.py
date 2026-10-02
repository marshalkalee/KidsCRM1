"""
Чьих детей видит родитель (TRU-135, TRU-136, TRU-141).

Единственный источник прав — контакты детей в CRM: ребёнок виден, если в
его карточке есть контакт (ChildContact) с этим номером — в телефонах
контакта или в поле WhatsApp. Считается заново на каждом запросе:
- мама и папа со своими номерами видят одного и того же ребёнка;
- плательщик и «просто контакт» видят одинаково — важна связь, не роль;
- отвязали контакт (или удалили родителя) — доступ пропал сразу;
- ребёнок ушёл из центра — история остаётся видна, пока контакт привязан.

Организация должна быть активна: отключённый центр в кабинете не виден.
"""

from django.db.models import Q

from domains.people.clients.models import Child, ChildContact, ParentContact


def contacts_for_phone(phone: str):
    """Карточки «Родитель» с этим номером — во всех активных центрах."""
    return ParentContact.objects.filter(
        Q(phones__number=phone, phones__deleted_at__isnull=True) | Q(whatsapp=phone),
        deleted_at__isnull=True,
        organization__is_active=True,
        organization__deleted_at__isnull=True,
    ).distinct()


def phone_is_known(phone: str) -> bool:
    return children_for_phone(phone).exists()


def children_for_phone(phone: str):
    links = ChildContact.objects.filter(
        parent_contact__in=contacts_for_phone(phone), deleted_at__isnull=True
    )
    return (
        Child.objects.filter(contacts__in=links, deleted_at__isnull=True)
        .select_related("organization")
        .distinct()
        .order_by("full_name")
    )


def child_for_phone(phone: str, child_id):
    """Ребёнок этого родителя или None — чужой и несуществующий неотличимы."""
    return children_for_phone(phone).filter(pk=child_id).first()
