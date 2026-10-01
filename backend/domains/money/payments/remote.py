"""
Удалённая оплата через Kaspi: счёт родителю (PaymentRequest) → оплата.

Пока счёт не оплачен, долг не меняется — в долге и выручке только
подтверждённые Payment (subscriptions/debt.py, analytics/metrics.py).
Оплаченный счёт создаёт обычную подтверждённую оплату через
KaspiPayProvider, ровно одну: повторный вебхук и двойной клик
«Оплата пришла» вернут ту же.
"""

from django.db import transaction
from django.utils import timezone

from domains.platform.core.audit import AuditLog
from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number
from domains.platform.core.utils import to_tenge
from domains.platform.tenants.org_settings import KASPI_PAYMENT_DETAILS, get_org_setting

from .kaspi import GatewayEvent, get_gateway
from .models import PaymentRequest
from .providers import KaspiPayProvider

NO_DETAILS_MESSAGE = (
    "Не указано, куда платить через Kaspi. Владелец может добавить ссылку Kaspi Pay "
    "или номер для перевода в настройках организации."
)


def payer_contact(organization, child):
    """Плательщик ребёнка (или первый контакт) и его телефон для Kaspi:
    мобильный, иначе WhatsApp, иначе любой."""
    from domains.people.clients.models import ChildContact

    links = (
        ChildContact.objects.for_tenant(organization)
        .filter(child=child, parent_contact__deleted_at__isnull=True)
        .select_related("parent_contact")
        .prefetch_related("parent_contact__phones")
        .order_by("-is_payer", "created_at")
    )
    link = links.first()
    if link is None:
        return None, ""
    parent = link.parent_contact
    phones = sorted(parent.phones.all(), key=lambda p: p.phone_type != p.PhoneType.MOBILE)
    phone = phones[0].number if phones else parent.whatsapp
    return parent, phone or ""


def channel_for(organization):
    """Как сейчас выставляется счёт и можно ли его выставить вообще."""
    gateway = get_gateway()
    details = get_org_setting(organization, KASPI_PAYMENT_DETAILS)
    if gateway:
        return {"channel": PaymentRequest.Channel.GATEWAY, "ready": True}
    return {"channel": PaymentRequest.Channel.LINK, "ready": bool(details)}


def _phone(phone: str) -> str:
    """+77011234567 → +7 701 123 45 67 — так номер читают в сообщении."""
    d = phone.lstrip("+")
    if len(d) == 11 and d.isdigit():
        return f"+{d[0]} {d[1:4]} {d[4:7]} {d[7:9]} {d[9:]}"
    return phone


def _money(amount) -> str:
    return f"{int(amount):,}".replace(",", " ") + " ₸"


def build_message(req: PaymentRequest, details: str = "") -> str:
    subscription = req.subscription
    greeting = (
        f"Здравствуйте, {req.parent_contact.full_name}!" if req.parent_contact else "Здравствуйте!"
    )
    name = subscription.subscription_type_version.name
    lines = [
        greeting,
        f"{subscription.organization.name}: оплата за «{name}» "
        f"({subscription.child.full_name}) — {_money(req.amount)}.",
    ]
    if req.channel == PaymentRequest.Channel.GATEWAY:
        lines.append(f"Счёт отправлен в приложение Kaspi.kz на номер {_phone(req.phone)}.")
        if req.pay_url:
            lines.append(f"Оплатить: {req.pay_url}")
    else:
        lines.append(f"Оплатить через Kaspi: {details}")
        lines.append("После оплаты, пожалуйста, пришлите чек.")
    lines.append("Спасибо!")
    return "\n".join(lines)


@transaction.atomic
def create_request(
    *, actor, subscription, amount, phone="", idempotency_key=None, base_url=""
) -> PaymentRequest:
    organization = subscription.organization
    if idempotency_key:
        existing = (
            PaymentRequest.objects.for_tenant(organization)
            .filter(idempotency_key=idempotency_key)
            .first()
        )
        if existing:
            return existing

    amount = to_tenge(amount)
    if amount <= 0:
        raise ValueError("Сумма счёта должна быть больше нуля.")

    parent, payer_phone = payer_contact(organization, subscription.child)
    try:
        phone = normalize_phone_number(phone or payer_phone)
    except InvalidPhoneNumberError as exc:
        raise ValueError("Укажите телефон родителя, на который выставить счёт.") from exc

    gateway = get_gateway()
    details = get_org_setting(organization, KASPI_PAYMENT_DETAILS)
    if gateway is None and not details:
        raise ValueError(NO_DETAILS_MESSAGE)

    req = PaymentRequest(
        organization=organization,
        subscription=subscription,
        parent_contact=parent,
        phone=phone,
        amount=amount,
        channel=PaymentRequest.Channel.GATEWAY if gateway else PaymentRequest.Channel.LINK,
        idempotency_key=idempotency_key,
        created_by=actor,
    )
    if gateway:
        # GatewayError поднимается дальше: счёт не сохранён, администратор
        # видит ошибку Kaspi и может повторить.
        invoice = gateway.create_invoice(request=req, base_url=base_url)
        req.external_id = invoice.external_id
        req.pay_url = invoice.pay_url
        req.expires_at = invoice.expires_at
        req.provider_raw_response = invoice.raw
    req.message = build_message(req, details)
    req.save()
    AuditLog.record(
        actor=actor,
        action=AuditLog.Action.CREATE,
        entity=req,
        after={"amount": str(amount), "phone": phone, "channel": req.channel},
    )
    return req


@transaction.atomic
def mark_paid(req: PaymentRequest, *, actor=None, transaction_id="", raw=None) -> PaymentRequest:
    """Деньги по счёту пришли: создать оплату (одну) и закрыть счёт.
    actor=None — подтвердил шлюз; оплату «принял» тот, кто выставил счёт.
    Оплата по отменённому или истёкшему счёту тоже записывается: деньги
    у центра, терять их нельзя."""
    req = PaymentRequest.objects.select_for_update().get(pk=req.pk)
    if req.status == PaymentRequest.Status.PAID:
        return req
    before = {"status": req.status}
    payment = KaspiPayProvider().record(
        subscription=req.subscription,
        amount=req.amount,
        actor=actor or req.created_by,
        comment="Счёт Kaspi" + (f" · {_phone(req.phone)}" if req.phone else ""),
        transaction_id=transaction_id or f"request:{req.pk}",
        raw_response=raw,
    )
    req.payment = payment
    req.status = PaymentRequest.Status.PAID
    req.paid_at = timezone.now()
    req.save(update_fields=["payment", "status", "paid_at", "updated_at"])
    AuditLog.record(
        actor=actor or req.created_by,
        action=AuditLog.Action.UPDATE,
        entity=req,
        before=before,
        after={"status": req.status, "payment": str(payment.pk), "by_gateway": actor is None},
    )
    return req


@transaction.atomic
def cancel_request(req: PaymentRequest, *, actor) -> PaymentRequest:
    req = PaymentRequest.objects.select_for_update().get(pk=req.pk)
    if req.status != PaymentRequest.Status.PENDING:
        raise ValueError("Отменить можно только счёт, который ждёт оплаты.")
    if req.external_id:
        gateway = get_gateway()
        if gateway:
            gateway.cancel_invoice(req.external_id)
    req.status = PaymentRequest.Status.CANCELLED
    req.cancelled_at = timezone.now()
    req.save(update_fields=["status", "cancelled_at", "updated_at"])
    AuditLog.record(
        actor=actor,
        action=AuditLog.Action.UPDATE,
        entity=req,
        before={"status": PaymentRequest.Status.PENDING},
        after={"status": req.status},
    )
    return req


_FINAL_FROM_GATEWAY = {
    GatewayEvent.CANCELLED: PaymentRequest.Status.CANCELLED,
    GatewayEvent.EXPIRED: PaymentRequest.Status.EXPIRED,
    GatewayEvent.FAILED: PaymentRequest.Status.FAILED,
}


def handle_event(event: GatewayEvent) -> PaymentRequest | None:
    """Сообщение шлюза о счёте. Неизвестный счёт — None (вебхук отвечает
    200, чтобы Kaspi не повторял его бесконечно)."""
    req = PaymentRequest.objects.filter(external_id=event.external_id).first()
    if req is None:
        return None
    if event.status == GatewayEvent.PAID:
        return mark_paid(
            req, transaction_id=event.transaction_id or event.external_id, raw=event.raw
        )
    new_status = _FINAL_FROM_GATEWAY.get(event.status)
    if new_status and req.status == PaymentRequest.Status.PENDING:
        req.status = new_status
        req.save(update_fields=["status", "updated_at"])
    return req


def expire_stale(organization) -> None:
    """Счета шлюза со сроком: просроченный ждущий счёт — «Истёк». Kaspi
    после срока оплату не примет; сообщения-ссылки срока не имеют."""
    PaymentRequest.objects.for_tenant(organization).filter(
        status=PaymentRequest.Status.PENDING, expires_at__lt=timezone.now()
    ).update(status=PaymentRequest.Status.EXPIRED, updated_at=timezone.now())
