"""
Контракт: Люди → Деньги и Продажи.

Владелец интерфейса: Анель (домен «Люди»). Менять сигнатуру и семантику —
только через владельца (PR с её ревью).
Потребители: импорт из Excel (создание/поиск детей и родителей при
загрузке базы центра, ТЗ п. 4.1) и конвертация заявки в домене «Продажи»
(перевод лида в статус «Пришёл на пробное»/«Купил», ТЗ п. 5.1).

Оба потребителя должны искать дубли по телефону перед созданием новой
записи — сервис не создаёт дубли сам по себе, это обязанность вызывающей
стороны: сначала find_duplicates, потом решение (создать/связать с
существующим), потом при необходимости create_with_parent.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class ParentRole(str, Enum):
    MOTHER = "mother"
    FATHER = "father"
    GUARDIAN = "guardian"
    OTHER = "other"


@dataclass(frozen=True)
class ParentInput:
    full_name: str
    phone: str
    role: ParentRole
    is_payer: bool = False


@dataclass(frozen=True)
class Child:
    id: int
    full_name: str
    birth_date: str  # ISO 8601 (YYYY-MM-DD)


class ChildService(ABC):
    @abstractmethod
    def find_duplicates(self, phone: str) -> list[Child]:
        """
        Ищет детей, у которых хотя бы одно контактное лицо имеет телефон,
        совпадающий с `phone` (нормализация формата — обязанность сервиса,
        потребитель передаёт телефон как ввёл пользователь/файл).

        Возвращает [] если совпадений нет — это не ошибка, это ожидаемый
        результат для нового клиента.
        """
        raise NotImplementedError

    @abstractmethod
    def create_with_parent(
        self,
        child_full_name: str,
        child_birth_date: str,
        parent: ParentInput,
        branch_id: int,
    ) -> Child:
        """
        Создаёт связку ребёнок+родитель одной операцией (см. ТЗ п. 3.1 —
        Parent ↔ Child всегда многие-ко-многим, ребёнок не существует без
        хотя бы одного контактного лица).

        Не проверяет дубли сама — вызывающая сторона обязана предварительно
        вызвать find_duplicates и осознанно решить создавать новую запись,
        а не связывать с найденной.

        Бросает исключение только на невалидных входных данных
        (например, пустой phone или отсутствующий branch_id) — бизнес-кейсов
        с «ожидаемой ошибкой» здесь нет, в отличие от SubscriptionService.consume.
        """
        raise NotImplementedError


class StubChildService(ChildService):
    """
    In-memory заглушка для разработки потребителей (импорт Excel, домен
    «Продажи») до готовности реальной реализации (Анель).
    """

    def __init__(self) -> None:
        self._children: dict[int, Child] = {}
        self._phones_by_child_id: dict[int, set[str]] = {}
        self._next_id = 1

    def seed_duplicate(self, phone: str, child: Child) -> None:
        """Подготовить фиктивного «существующего» ребёнка для теста find_duplicates."""
        self._children[child.id] = child
        self._phones_by_child_id.setdefault(child.id, set()).add(phone)

    def find_duplicates(self, phone: str) -> list[Child]:
        return [
            self._children[child_id]
            for child_id, phones in self._phones_by_child_id.items()
            if phone in phones
        ]

    def create_with_parent(
        self,
        child_full_name: str,
        child_birth_date: str,
        parent: ParentInput,
        branch_id: int,
    ) -> Child:
        child = Child(id=self._next_id, full_name=child_full_name, birth_date=child_birth_date)
        self._children[child.id] = child
        self._phones_by_child_id.setdefault(child.id, set()).add(parent.phone)
        self._next_id += 1
        return child
