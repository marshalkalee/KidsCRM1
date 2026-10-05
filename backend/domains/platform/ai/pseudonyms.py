"""
Псевдонимы для внешней модели (ADR-0008, вариант «а»; решение 05.10.2026).

Имена детей, родителей и контактов заявок не уходят наружу: перед отправкой
каждое известное центру имя — целиком и по частям — заменяется меткой
вида [N12], ответ модели проходит обратную замену. Сотрудник видит имена,
модель — только метки. Сопоставление живёт у нас: в памяти на один
запрос, у чата — в переписке (AIConversation.pseudonyms), чтобы метка
одного человека не менялась от вопроса к вопросу.

Ищем по именам, а не по названиям полей: имя в комментарии, заметке о
звонке или вопросе сотрудника заменяется так же, как в поле child_name.
Склонённые формы («Исаевой Сафией», «Айгериму»)
ловятся по основе с падежным окончанием — только с заглавной буквы, чтобы
имя «Мира» не забирало слово «миру». Метка склонённой формы — та же, что
у именительной: ответ модели вернётся с именем в именительном падеже.

Имена сотрудников не заменяются: это не данные клиентов, а модели нужно
понимать, кто ответственный.
"""

import re
import threading

from domains.people.clients.models import Child, ParentContact
from domains.platform.leads.models import Lead

TOKEN = re.compile(r"\[N\d+\]")
MIN_PART = 3
# Основа для склонений — от 3 букв: «Ева» склоняется только целиком.
MIN_STEM = 3
VOWEL_END = "аяыиеоуюйь"
# Падежные окончания имён и фамилий (рус.), длинные — первыми.
ENDINGS = (
    "ого",
    "его",
    "ому",
    "ему",
    "ой",
    "ей",
    "ою",
    "ею",
    "ом",
    "ем",
    "ым",
    "им",
    "ую",
    "юю",
    "ая",
    "яя",
    "а",
    "я",
    "ы",
    "и",
    "е",
    "у",
    "ю",
)

# Добавляется к системному промпту каждой функции.
INSTRUCTION = (
    "Имена людей в данных заменены метками вида [N12]. Пиши метки ровно так, "
    "как они даны: в квадратных скобках, без склонения и изменений, не пытайся "
    "угадать имя. Обращение к родителю — тоже меткой."
)


def _names(organization) -> set[str]:
    raw = set()
    raw.update(
        Child.objects.all_with_deleted()
        .filter(organization=organization)
        .values_list("full_name", flat=True)
    )
    raw.update(
        ParentContact.objects.all_with_deleted()
        .filter(organization=organization)
        .values_list("full_name", flat=True)
    )
    for parent, child in (
        Lead.objects.all_with_deleted()
        .filter(organization=organization)
        .values_list("parent_name", "child_name")
    ):
        raw.update((parent, child))
    names = set()
    for name in raw:
        name = " ".join((name or "").split())
        if not name:
            continue
        names.add(name)
        # Часть имени — отдельно: «Алия пропустила», «мама Бековой Алии»
        # не узнать по полному «Бекова Алия».
        names.update(part for part in name.split(" ") if len(part) >= MIN_PART)
    return names


class Pseudonymizer:
    def __init__(self, organization, mapping=None):
        # token → имя; продолжаем нумерацию сохранённого сопоставления.
        self.to_real = dict(mapping or {})
        # Чистка импорта шлёт куски файла параллельно — номера меток не должны
        # совпасть у двух разных имён.
        self._lock = threading.Lock()
        self.to_token = {real.casefold(): token for token, real in self.to_real.items()}
        names = sorted(_names(organization), key=len, reverse=True)
        self._canonical = {}
        for name in names:
            self._canonical.setdefault(name.casefold(), name)
        self._pattern = (
            re.compile(
                r"(?<!\w)(" + "|".join(re.escape(n) for n in names) + r")(?!\w)", re.IGNORECASE
            )
            if names
            else None
        )
        # Основа → имя в именительном падеже: «Исаев» → «Исаева».
        self._stems = {}
        for name in names:
            if " " in name or len(name) < MIN_STEM + 1:
                continue
            stem = name[:-1] if name[-1].lower() in VOWEL_END else name
            if len(stem) >= MIN_STEM:
                self._stems.setdefault(stem, name)
        self._declined = (
            re.compile(
                r"(?<!\w)("
                + "|".join(re.escape(s) for s in sorted(self._stems, key=len, reverse=True))
                + r")("
                + "|".join(ENDINGS)
                + r")(?!\w)"
            )
            if self._stems
            else None
        )

    @property
    def mapping(self) -> dict:
        return dict(self.to_real)

    def _token(self, name: str) -> str:
        key = name.casefold()
        with self._lock:
            token = self.to_token.get(key)
            if token is None:
                token = f"[N{len(self.to_real) + 1}]"
                self.to_token[key] = token
                self.to_real[token] = self._canonical.get(key, name)
            return token

    def mask(self, value):
        """Строка, список или словарь → то же с метками вместо имён."""
        if isinstance(value, str):
            if self._pattern is not None:
                value = self._pattern.sub(lambda m: self._token(m.group(0)), value)
            if self._declined is not None:
                value = self._declined.sub(lambda m: self._token(self._stems[m.group(1)]), value)
            return value
        if isinstance(value, list):
            return [self.mask(v) for v in value]
        if isinstance(value, dict):
            return {k: self.mask(v) for k, v in value.items()}
        return value

    def unmask(self, value):
        """Метки модели → имена. Незнакомая метка остаётся как есть."""
        if isinstance(value, str):
            return TOKEN.sub(lambda m: self.to_real.get(m.group(0), m.group(0)), value)
        if isinstance(value, list):
            return [self.unmask(v) for v in value]
        if isinstance(value, dict):
            return {k: self.unmask(v) for k, v in value.items()}
        return value
