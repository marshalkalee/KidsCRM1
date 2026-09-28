"""
Значения справочников по умолчанию (ТЗ п. 5.1; TRU-93). Заводятся у каждой
новой организации (signals.py) и миграцией 0003 — у уже существующих.
Дальше центр правит их сам: переименовывает, добавляет, архивирует.
"""

from .models import LeadRejectionReason, LeadSource

DEFAULT_SOURCES = ["Instagram", "WhatsApp", "Сайт", "Звонок", "Рекомендация", "Офлайн", "Другое"]
DEFAULT_REJECTION_REASONS = [
    "Дорого",
    "Неудобное время",
    "Далеко",
    "Не подошло направление",
    "Не пришёл на пробное",
    "Другое",
]


def ensure_default_dictionaries(
    organization, source_model=LeadSource, reason_model=LeadRejectionReason
):
    """Идемпотентно: справочник, где уже есть хоть одно значение, не трогаем.
    Модели передаются параметрами — миграция данных зовёт с историческими."""
    for model, names in (
        (source_model, DEFAULT_SOURCES),
        (reason_model, DEFAULT_REJECTION_REASONS),
    ):
        if model.objects.filter(organization=organization).exists():
            continue
        model.objects.bulk_create(model(organization=organization, name=name) for name in names)
