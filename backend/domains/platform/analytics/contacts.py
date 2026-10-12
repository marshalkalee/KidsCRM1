"""Контакт родителя для списков «кому позвонить»: риск-лист (TRU-122) и
отток (TRU-127). Один выбор на оба списка: основной контакт ребёнка (иначе
первый по роли), его первый телефон, WhatsApp — свой номер или телефон."""

from domains.people.clients.models import ChildContact, ContactPhone


def parent_contacts(organization, child_ids) -> dict:
    """{child_id: {"parent", "phone", "whatsapp"}} — только у кого есть контакт."""
    links = (
        ChildContact.objects.for_tenant(organization)
        .filter(child_id__in=child_ids)
        .select_related("parent_contact")
        .order_by("child_id", "-is_primary_contact", "role")
    )
    parents = {}
    for link in links:
        parents.setdefault(link.child_id, link.parent_contact)
    phones = {}
    for phone in ContactPhone.objects.for_tenant(organization).filter(
        parent_contact_id__in=[parent.id for parent in parents.values()]
    ):
        phones.setdefault(phone.parent_contact_id, phone.number)
    return {
        child_id: {
            "parent": parent.full_name,
            "phone": phones.get(parent.id),
            "whatsapp": parent.whatsapp or phones.get(parent.id),
        }
        for child_id, parent in parents.items()
    }
