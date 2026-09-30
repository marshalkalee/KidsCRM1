"""
Значения справочников по умолчанию (ТЗ п. 5.1; TRU-93). Заводятся у каждой
новой организации (signals.py) и миграциями 0003/0005 — у уже существующих.
Дальше центр правит их сам: переименовывает, добавляет, архивирует.
"""

from .models import LeadKind, LeadRejectionReason, LeadSource

DEFAULT_SOURCES = ["Instagram", "WhatsApp", "Сайт", "Звонок", "Рекомендация", "Офлайн", "Другое"]
DEFAULT_REJECTION_REASONS = [
    "Дорого",
    "Неудобное время",
    "Далеко",
    "Не подошло направление",
    "Не пришёл на пробное",
    "Другое",
]
# Эти причины — потеря контакта, а не возражение (TRU-117).
LOST_CONTACT_REASONS = {"Не пришёл на пробное"}
# Отказ от продления (TRU-98) — клиент уже свой, причины другие.
DEFAULT_RENEWAL_REJECTION_REASONS = [
    "Дорого",
    "Ушли из центра",
    "Сменили направление",
    "Переезд",
    "Другое",
]


def ensure_default_dictionaries(
    organization, source_model=LeadSource, reason_model=LeadRejectionReason
):
    """Идемпотентно: справочник, где уже есть хоть одно значение, не трогаем.
    Модели передаются параметрами — миграция данных зовёт с историческими."""
    if not source_model.objects.filter(organization=organization).exists():
        source_model.objects.bulk_create(
            source_model(organization=organization, name=name) for name in DEFAULT_SOURCES
        )
    for kind, names in (
        (LeadKind.NEW, DEFAULT_REJECTION_REASONS),
        (LeadKind.RENEWAL, DEFAULT_RENEWAL_REJECTION_REASONS),
    ):
        if reason_model.objects.filter(organization=organization, kind=kind).exists():
            continue
        reason_model.objects.bulk_create(
            reason_model(
                organization=organization,
                name=name,
                kind=kind,
                is_lost_contact=kind == LeadKind.NEW and name in LOST_CONTACT_REASONS,
            )
            for name in names
        )
