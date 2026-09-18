"""
Контракт: Деньги → всем.

Владелец интерфейса: Bekzat (домен «Деньги»). Менять сигнатуру и семантику —
только через владельца (PR с его ревью).
Потребители: все домены — единый аудит-лог критичных действий (изменение
оплат, удаление посещений, изменение абонементов, ТЗ п. 2) вместо трёх
независимых копий в трёх доменах.

Лежит в apps/core, а не apps/payments — это сознательно: сервис общий для
всех доменов, а не приватная деталь домена «Деньги». Владение интерфейсом
(кто может менять сигнатуру) и место кода (где физически лежит реализация)
— разные вопросы.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AuditEntity:
    # Например: type="payment", id="42" или type="subscription", id="17".
    type: str
    id: str


class AuditLog(ABC):
    @abstractmethod
    def record(
        self,
        actor: Any,
        action: str,
        entity: AuditEntity,
        before: dict | None,
        after: dict | None,
    ) -> None:
        """
        Фиксирует одно критичное действие. Параметры:
        - actor — кто совершил действие (пользователь системы; тип уточнится
          при появлении модели User, сейчас — любой объект с id/строковое
          представление, сервис не завязывается на конкретный класс).
        - action — machine-readable код действия, namespaced по домену,
          например "payments.update", "attendance.edit_backdated",
          "subscriptions.freeze". Владелец интерфейса не ведёт реестр всех
          возможных action — это ответственность вызывающих доменов, но
          формат "domain.verb" обязателен для читаемости логов.
        - entity — что изменено.
        - before / after — снимки состояния до/после в виде dict, готового
          к сериализации в JSON. None допустим для before при создании и
          для after при удалении.

        Ничего не возвращает и не бросает исключений на ожидаемых входных
        данных — запись аудита не должна быть точкой отказа бизнес-операции.
        Если запись физически не удалась (например, БД недоступна) — это
        решается на уровне реализации (retry/очередь), не контрактом.
        """
        raise NotImplementedError


class StubAuditLog(AuditLog):
    """
    In-memory заглушка для разработки потребителей (все домены) до
    готовности реальной реализации (Bekzat). Хранит записи в списке —
    удобно для ассертов в тестах вызывающей стороны.
    """

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record(
        self,
        actor: Any,
        action: str,
        entity: AuditEntity,
        before: dict | None,
        after: dict | None,
    ) -> None:
        self.records.append(
            {
                "actor": actor,
                "action": action,
                "entity": entity,
                "before": before,
                "after": after,
            }
        )
