"""
Уведомления в кабинете родителя (TRU-172): push на устройства, какие типы
получать, «отключить всё». Отправляет только центр рассылок
(platform.notifications.messaging); здесь — то, что родитель решает сам.

Родитель сам включает напоминания — это и есть его согласие на служебные
сообщения от всех его центров (ADR-0010, п. 4: источник «сам в кабинете»).
«Отключить всё» — отписка от служебных и рекламных во всех центрах и
удаление подписок всех его устройств.
"""

from django.conf import settings
from django.db import transaction

from domains.platform.notifications.messaging.events import EVENTS
from domains.platform.notifications.messaging.service import consent_status, set_consent
from domains.platform.notifications.models import MessageCategory, MessagingConsent

from . import access
from .auth import LoginError
from .models import PushSubscription


def _contacts(account):
    return list(access.contacts_for_phone(account.phone).select_related("organization"))


def status(account, endpoint: str = "") -> dict:
    contacts = _contacts(account)
    statuses = {consent_status(c, MessageCategory.UTILITY) for c in contacts}
    prefs = account.notification_prefs or {}
    return {
        "public_key": settings.WEBPUSH_VAPID_PUBLIC_KEY,
        # Включено, если хоть один центр может писать: согласие есть и не все отписаны.
        "enabled": MessagingConsent.Status.OPTED_IN in statuses,
        "this_device": bool(endpoint)
        and account.push_subscriptions.filter(endpoint=endpoint).exists(),
        "devices": account.push_subscriptions.count(),
        "events": [
            {"key": e.key, "label": e.label, "enabled": prefs.get(e.key) is not False}
            for e in EVENTS.values()
        ],
    }


def _consent_everywhere(account, status_value, categories):
    for contact in _contacts(account):
        for category in categories:
            if consent_status(contact, category) != status_value:
                set_consent(contact, category, status_value, MessagingConsent.Source.PARENT_PORTAL)


@transaction.atomic
def subscribe(account, data: dict, user_agent: str = "") -> dict:
    endpoint = (data.get("endpoint") or "").strip()
    keys = data.get("keys") or {}
    if not endpoint.startswith("https://") or not keys.get("p256dh") or not keys.get("auth"):
        raise LoginError("Браузер не дал подписку на уведомления — попробуйте ещё раз.")
    # Тот же браузер мог быть подписан под другим номером — теперь он этого родителя.
    PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            "account": account,
            "p256dh": keys["p256dh"][:255],
            "auth": keys["auth"][:255],
            "user_agent": user_agent[:255],
        },
    )
    _consent_everywhere(account, MessagingConsent.Status.OPTED_IN, [MessageCategory.UTILITY])
    return status(account, endpoint)


def unsubscribe_device(account, endpoint: str) -> dict:
    account.push_subscriptions.filter(endpoint=endpoint).delete()
    return status(account, endpoint)


@transaction.atomic
def update(account, *, enabled=None, events=None, endpoint="") -> dict:
    """Профиль: какие типы получать, включить или отключить всё."""
    if events is not None:
        if not isinstance(events, dict) or any(key not in EVENTS for key in events):
            raise LoginError("Неизвестный тип уведомления.")
        prefs = dict(account.notification_prefs or {})
        for key, value in events.items():
            if value:
                prefs.pop(key, None)
            else:
                prefs[key] = False
        account.notification_prefs = prefs
        account.save(update_fields=["notification_prefs"])
    if enabled is True:
        _consent_everywhere(account, MessagingConsent.Status.OPTED_IN, [MessageCategory.UTILITY])
    elif enabled is False:
        account.push_subscriptions.all().delete()
        _consent_everywhere(
            account,
            MessagingConsent.Status.OPTED_OUT,
            [MessageCategory.UTILITY, MessageCategory.MARKETING],
        )
    return status(account, endpoint)
