"""
Контракт: Расписание → всем.

Владелец интерфейса: Дарья (домен «Расписание»). Менять сигнатуру и
семантику — только через владельца (PR с её ревью).
Потребители: домен «Деньги» — отработки пропущенных занятий (M1, ТЗ п. 4.3),
домен «Продажи» — запись на пробное занятие (M2, ТЗ п. 5.1). Один механизм
обслуживает оба случая через параметр `kind`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class EnrollKind(str, Enum):
    MAKEUP = "makeup"  # отработка
    TRIAL = "trial"  # пробное


class EnrollStatus(str, Enum):
    ENROLLED = "enrolled"
    LESSON_FULL = "lesson_full"
    ALREADY_ENROLLED = "already_enrolled"
    LESSON_NOT_FOUND = "lesson_not_found"
    CHILD_NOT_FOUND = "child_not_found"


@dataclass(frozen=True)
class EnrollResult:
    status: EnrollStatus
    enrollment_id: int | None = None


class LessonService(ABC):
    @abstractmethod
    def enroll(self, lesson_id: int, child_id: int, kind: EnrollKind) -> EnrollResult:
        """
        Записывает ребёнка `child_id` на занятие `lesson_id` «поверх» группы —
        запись помечена `kind` (отработка/пробное) и не превращается в
        постоянную запись в группу.

        Контроль вместимости обязателен: если у занятия (зала/группы) нет
        свободных мест, возвращается LESSON_FULL, а не исключение — это
        ожидаемый бизнес-исход, администратор должен увидеть его и предложить
        другое занятие, а не получить 500-ю ошибку.

        Возвращает EnrollResult.status:
        - ENROLLED — запись создана, enrollment_id заполнен.
        - LESSON_FULL — вместимость исчерпана.
        - ALREADY_ENROLLED — ребёнок уже записан на это занятие (в т.ч. как
          основной участник группы) — повторная запись не создаётся.
        - LESSON_NOT_FOUND / CHILD_NOT_FOUND — переданы несуществующие id;
          это тоже возвращается как статус, а не исключение, чтобы вызывающая
          сторона (например, обработчик формы) могла показать сообщение без
          try/except на каждый вызов.

        Не проверяет право ребёнка на отработку (есть ли у него абонемент,
        не истёк ли срок отработки) — это ответственность вызывающей стороны
        (домен «Деньги» для kind=MAKEUP) до вызова enroll.
        """
        raise NotImplementedError


class StubLessonService(LessonService):
    """
    In-memory заглушка для разработки потребителей (домены «Деньги» и
    «Продажи») до готовности реальной реализации (Дарья).
    """

    def __init__(self, capacity_per_lesson: int = 10) -> None:
        self._capacity = capacity_per_lesson
        self._enrollments: dict[int, list[int]] = {}
        self._next_id = 1

    def enroll(self, lesson_id: int, child_id: int, kind: EnrollKind) -> EnrollResult:
        enrolled_children = self._enrollments.setdefault(lesson_id, [])

        if child_id in enrolled_children:
            return EnrollResult(status=EnrollStatus.ALREADY_ENROLLED)

        if len(enrolled_children) >= self._capacity:
            return EnrollResult(status=EnrollStatus.LESSON_FULL)

        enrolled_children.append(child_id)
        enrollment_id = self._next_id
        self._next_id += 1
        return EnrollResult(status=EnrollStatus.ENROLLED, enrollment_id=enrollment_id)
