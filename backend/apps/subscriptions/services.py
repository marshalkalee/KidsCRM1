"""
Контракт: Расписание → Деньги.

Владелец интерфейса: Bekzat (домен «Деньги»). Менять сигнатуру и семантику
статусов — только через владельца (PR с его ревью).
Потребитель: Дарья (домен «Расписание») — вызывает `consume()` при отметке
посещения «пришёл», чтобы списать занятие с активного абонемента.

До готовности реальной реализации потребитель работает через
`StubSubscriptionService` ниже — интерфейс `SubscriptionService` при этом
не меняется.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class ConsumeStatus(str, Enum):
    CONSUMED = "consumed"
    NO_ACTIVE_SUBSCRIPTION = "no_active_subscription"
    SUBSCRIPTION_EXHAUSTED = "subscription_exhausted"
    RULE_FORBIDS_CONSUMPTION = "rule_forbids_consumption"


@dataclass(frozen=True)
class ConsumeResult:
    status: ConsumeStatus
    subscription_id: int | None = None
    remaining_lessons: int | None = None
    # Заполняется для RULE_FORBIDS_CONSUMPTION — например, «правило типа
    # абонемента не разрешает списание за отработку».
    reason: str | None = None


class SubscriptionService(ABC):
    @abstractmethod
    def consume(self, child_id: int, lesson_id: int) -> ConsumeResult:
        """
        Списывает занятие `lesson_id` с активного абонемента ребёнка `child_id`.

        Вызывается ровно один раз на отметку посещения «пришёл» — идемпотентность
        повторного вызова для той же пары (child_id, lesson_id) гарантирует
        реализация, а не потребитель.

        Возвращает ConsumeResult.status:
        - CONSUMED — списано, remaining_lessons заполнен.
        - NO_ACTIVE_SUBSCRIPTION — у ребёнка нет активного абонемента на
          это направление/группу. Потребитель должен выставить визуальный
          флаг «занятие без абонемента» и создать задачу администратору
          (см. ТЗ п. 4.3) — это делает потребитель, не сервис.
        - SUBSCRIPTION_EXHAUSTED — абонемент найден, но занятия исчерпаны.
        - RULE_FORBIDS_CONSUMPTION — правило типа абонемента запрещает
          списание в этой ситуации (например, отработка не входит в пакет);
          reason содержит человекочитаемое объяснение.

        Не бросает исключения на бизнес-случаях выше — это ожидаемые
        исходы, а не ошибки. Исключение допустимо только при неверных
        идентификаторах (child_id/lesson_id не существуют).
        """
        raise NotImplementedError


class StubSubscriptionService(SubscriptionService):
    """
    Детерминированная заглушка для разработки потребителя (Дарья) до
    готовности реальной реализации (Bekzat). Не содержит бизнес-логики
    списания — только фиксированные/настраиваемые ответы.
    """

    def __init__(self, default_status: ConsumeStatus = ConsumeStatus.CONSUMED) -> None:
        self._default_status = default_status
        self._overrides: dict[tuple[int, int], ConsumeResult] = {}

    def set_result_for(self, child_id: int, lesson_id: int, result: ConsumeResult) -> None:
        """Задать конкретный ответ для пары (child_id, lesson_id) — для тестов веток."""
        self._overrides[(child_id, lesson_id)] = result

    def consume(self, child_id: int, lesson_id: int) -> ConsumeResult:
        override = self._overrides.get((child_id, lesson_id))
        if override is not None:
            return override

        if self._default_status is ConsumeStatus.CONSUMED:
            return ConsumeResult(
                status=ConsumeStatus.CONSUMED, subscription_id=1, remaining_lessons=9
            )
        return ConsumeResult(status=self._default_status)
