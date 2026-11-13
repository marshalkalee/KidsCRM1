"""
Кнопки «WhatsApp» в кабинете родителя: куда писать центру.

Если у центра подключён номер WhatsApp (по QR-коду или Meta), кнопка ведёт
на него — сообщение родителя сразу попадает в чат CRM. Порядок: номер
филиала ребёнка, номер всего центра, телефон филиала из настроек (как
раньше, когда WhatsApp не подключён), любой подключённый номер центра.
"""

from urllib.parse import quote


def _digits(phone: str) -> str:
    return "".join(ch for ch in phone or "" if ch.isdigit())


def connected_numbers(organization) -> dict:
    """{branch_id или None (весь центр): номер} подключённых номеров."""
    from domains.platform.notifications.models import WhatsAppConnection

    rows = (
        WhatsAppConnection.objects.for_tenant(organization)
        .filter(status=WhatsAppConnection.Status.CONNECTED)
        .exclude(business_phone="")
        .values_list("branch_id", "business_phone")
    )
    return dict(rows)


def number_for(numbers: dict, branch_id=None, fallback_phone: str = "") -> str:
    if branch_id and numbers.get(branch_id):
        return numbers[branch_id]
    if numbers.get(None):
        return numbers[None]
    if fallback_phone:
        return fallback_phone
    return next(iter(numbers.values()), "")


def url(phone: str, text: str = "") -> str:
    digits = _digits(phone)
    if not digits:
        return ""
    return f"https://wa.me/{digits}?text={quote(text)}" if text else f"https://wa.me/{digits}"
