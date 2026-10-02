"""
Шлюз Kaspi для удалённой оплаты (канал PaymentRequest.Channel.GATEWAY).

Счёт уходит в Kaspi на телефон родителя, родитель платит в приложении
Kaspi.kz, Kaspi сообщает об оплате вебхуком — CRM сама создаёт оплату.

Какой шлюз работает — настройка KASPI_PAY_GATEWAY:
- "" (по умолчанию) — шлюза нет, счета идут каналом LINK: сообщение
  родителю с реквизитами Kaspi центра, оплату подтверждает администратор;
- "fake" — тестовый шлюз для стенда и тестов: «оплатить» можно на
  странице /pay/test/<номер счёта>. На проде не включать.

Настоящий Kaspi подключается отдельным классом с тем же интерфейсом
(KaspiGateway) после договора с Kaspi на приём удалённых платежей: адреса,
формат запросов и подпись вебхука Kaspi выдаёт вместе с доступом, поэтому
здесь их нет — придумывать формат чужого API нельзя (docs/project-status.md).
"""

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone


class GatewayError(Exception):
    """Kaspi не принял счёт или недоступен — текст показывается администратору."""


class WebhookRejected(Exception):
    """Вебхук без верной подписи или с непонятным телом."""


@dataclass
class Invoice:
    external_id: str
    pay_url: str = ""
    expires_at: datetime | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class GatewayEvent:
    """Что Kaspi сообщил о счёте: paid / cancelled / expired / failed."""

    external_id: str
    status: str
    transaction_id: str = ""
    raw: dict = field(default_factory=dict)

    PAID = "paid"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FAILED = "failed"


class KaspiGateway:
    name = ""

    def create_invoice(self, *, request, base_url: str) -> Invoice:
        raise NotImplementedError

    def cancel_invoice(self, external_id: str) -> None:
        raise NotImplementedError

    def parse_webhook(self, body: bytes, headers) -> GatewayEvent:
        raise NotImplementedError


class FakeKaspiGateway(KaspiGateway):
    """Ведёт себя как Kaspi, но без Kaspi: счёт «выставляется» сразу, а
    оплатить его можно на тестовой странице. Вебхук — тело JSON, подпись
    HMAC-SHA256 тела ключом KASPI_PAY_WEBHOOK_SECRET в X-Kaspi-Signature."""

    name = "fake"
    SIGNATURE_HEADER = "X-Kaspi-Signature"

    def create_invoice(self, *, request, base_url: str) -> Invoice:
        external_id = f"fake-{uuid.uuid4().hex}"
        hours = settings.KASPI_PAY_INVOICE_TTL_HOURS
        return Invoice(
            external_id=external_id,
            pay_url=f"{base_url.rstrip('/')}/pay/test/{external_id}",
            expires_at=timezone.now() + timedelta(hours=hours),
            raw={"gateway": self.name},
        )

    def cancel_invoice(self, external_id: str) -> None:
        return None

    @staticmethod
    def sign(body: bytes) -> str:
        secret = settings.KASPI_PAY_WEBHOOK_SECRET.encode()
        return hmac.new(secret, body, hashlib.sha256).hexdigest()

    def parse_webhook(self, body: bytes, headers) -> GatewayEvent:
        if not settings.KASPI_PAY_WEBHOOK_SECRET:
            raise WebhookRejected("Не задан KASPI_PAY_WEBHOOK_SECRET")
        signature = headers.get(self.SIGNATURE_HEADER, "")
        if not hmac.compare_digest(signature, self.sign(body)):
            raise WebhookRejected("Неверная подпись")
        try:
            data = json.loads(body)
            return GatewayEvent(
                external_id=str(data["invoice_id"]),
                status=str(data["status"]),
                transaction_id=str(data.get("transaction_id", "")),
                raw=data,
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise WebhookRejected("Непонятное тело вебхука") from exc


GATEWAYS = {FakeKaspiGateway.name: FakeKaspiGateway}


def get_gateway() -> KaspiGateway | None:
    name = settings.KASPI_PAY_GATEWAY
    if not name:
        return None
    try:
        return GATEWAYS[name]()
    except KeyError as exc:
        raise GatewayError(f"Неизвестный шлюз Kaspi: {name}") from exc
