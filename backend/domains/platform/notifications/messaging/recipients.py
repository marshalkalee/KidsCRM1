"""Родитель в CRM (ParentContact) → его аккаунты кабинета (по любому номеру).
Аккаунт общий для всех центров (ParentAccount — по телефону): язык кабинета,
отключённые типы уведомлений, push-подписки устройств."""

from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number


def parent_phones(parent) -> set[str]:
    phones = [parent.whatsapp, *parent.phones.values_list("number", flat=True)]
    normalized = set()
    for phone in phones:
        try:
            if phone:
                normalized.add(normalize_phone_number(phone))
        except InvalidPhoneNumberError:
            continue
    return normalized


def accounts_for_parent(parent):
    from domains.people.portal.models import ParentAccount

    return ParentAccount.objects.filter(phone__in=parent_phones(parent))
