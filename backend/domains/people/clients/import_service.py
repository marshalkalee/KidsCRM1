"""
Импорт детей из Excel/CSV (ТЗ п. 4.1, MVP критерий приёмки №1: "дубли
выявлены при импорте") — первый из трёх потребителей ChildService
(services.py, TRU-8 контракт №2). Не своя копия поиска дублей — весь
дедуп идёт через ChildService.find_duplicates(), иначе этот экран и
будущая конвертация заявки (M2) посчитают дубли по-разному.

Откуда берутся колонки файла (маппинг, автоугадывание, чтение
.xlsx/.csv) — column_mapping.py. Здесь — только то, что происходит
ПОСЛЕ маппинга: очистка "грязных" значений одного поля (build_row) и
дедуп/создание записей (resolve_rows/execute_import), не зависящие от
того, был ли файл .xlsx с фиксированными колонками или .csv с
маппингом мышью.

Дедуп внутри файла и второй ребёнок в семье внутри ОДНОГО файла — тот же
сценарий из ТЗ ("тот же телефон, другой ребёнок"), просто оба ребёнка
приходят в одном файле, а не по одному через веб-форму: строки
обрабатываются по порядку, и телефон, once встреченный, "запоминается"
на время предпросмотра/выполнения (см. _PhoneResolutionMap) — второй
ребёнок в файле с тем же номером не создаёт вторую маму.

Ошибки vs предупреждения (ТЗ п. 4.1, тикет «валидация, сухой прогон и
отчёт об ошибках»): ошибка (ImportRow.errors) блокирует строку — она не
попадёт в базу даже при выполнении импорта. Предупреждение
(ImportRow.warnings) — слабое совпадение по ФИО, дубль (пропускается, но
это не поломка данных), несуществующее направление/группа — строку не
блокирует, только помечает для ручной проверки. Оба списка собираются в
build_dry_run_report() для отчёта сухого прогона (tasks.py).
"""

import datetime
import re
from dataclasses import dataclass, field

from django.db.models import Q

from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number

from .models import Child, ChildContact, ParentContact
from .services import ChildService, DuplicateReason


def _existing_family_child_keys(organization, phone):
    """(имя.lower(), дата рождения) уже существующих детей всех
    ParentContact с этим телефоном — используется, чтобы засеять
    _PhoneResolutionMap реальным состоянием базы в момент, когда телефон
    впервые встретился в файле: без этого второй ряд файла с тем же
    телефоном сверялся бы только с детьми из ЭТОГО файла, забывая, что
    у найденной семьи уже есть свои дети в базе (см. resolve_rows)."""
    parent_ids = ParentContact.objects.for_tenant(organization).filter(
        Q(phones__number=phone) | Q(whatsapp=phone)
    )
    children = Child.objects.for_tenant(organization).filter(
        contacts__parent_contact__in=parent_ids
    )
    return {(c.full_name.lower(), c.birth_date) for c in children}


GENDER_ALIASES = {
    "м": Child.Gender.MALE,
    "мужской": Child.Gender.MALE,
    "male": Child.Gender.MALE,
    "ж": Child.Gender.FEMALE,
    "женский": Child.Gender.FEMALE,
    "female": Child.Gender.FEMALE,
}
ROLE_ALIASES = {label.lower(): value for value, label in ChildContact.Role.choices}
ROLE_ALIASES.update(
    {
        "мама": ChildContact.Role.MOTHER,
        "папа": ChildContact.Role.FATHER,
        "бабушка": ChildContact.Role.GRANDMOTHER,
        "опекун": ChildContact.Role.GUARDIAN,
    }
)

# "мама Айгерим" вместо чистого ФИО в колонке родителя — реальная грязь
# из ТЗ (найдено на синтетических файлах, см. docs/import_format.md).
# Роль-префикс отделяется от имени и используется, только если отдельная
# колонка "Роль родителя" не задана явно (она приоритетнее).
_ROLE_PREFIX_RE = re.compile(
    r"^("
    + "|".join(re.escape(k) for k in sorted(ROLE_ALIASES, key=len, reverse=True))
    + r")\s+(.+)$",
    re.IGNORECASE,
)


def _split_role_prefix(raw_name: str) -> tuple[str | None, str]:
    match = _ROLE_PREFIX_RE.match(raw_name.strip())
    if not match:
        return None, raw_name
    prefix, rest = match.groups()
    return ROLE_ALIASES.get(prefix.lower()), rest.strip()


# Несколько телефонов в одной ячейке через запятую/точку с запятой/слэш/
# "и" — тоже реальная грязь (родитель и его партнёр в одной колонке).
# ContactPhone — отдельная модель (не одно поле), поэтому все валидные
# номера сохраняются, не только первый.
_PHONE_SPLIT_RE = re.compile(r"[,;/]+|\s+и\s+", re.IGNORECASE)


def _split_phones(raw: str) -> list[str]:
    parts = [p.strip() for p in _PHONE_SPLIT_RE.split(raw) if p.strip()]
    return parts or ([raw.strip()] if raw.strip() else [])


class RowAction:
    CREATE_NEW_FAMILY = "create_new_family"
    ATTACH_EXISTING = "attach_existing"
    SKIP = "skip"
    ERROR = "error"


@dataclass
class ImportRow:
    row_number: int  # номер строки в файле (для сообщений администратору)
    child_name: str = ""
    birth_date: datetime.date | None = None
    gender: str = ""
    parent_name: str = ""
    phone: str = ""  # первый валидный номер — используется для дедупа
    extra_phones: list[str] = field(
        default_factory=list
    )  # остальные валидные номера из той же ячейки
    role: str = ChildContact.Role.OTHER
    medical_notes: str = ""
    # Сырое значение колонки "Остаток занятий" — не превращается в
    # реальный Subscription при импорте (решение зафиксировано в
    # docs/import_format.md: перенос остатков — отдельная задача домена
    # Bekzat'а), но и не отбрасывается молча — видно в отчёте импорта,
    # чтобы не всплыло на приёмке.
    reported_balance: str = ""
    # Сырые названия из колонок "Направление"/"Группа" (если сопоставлены) —
    # используются только для предупреждения в отчёте сухого прогона
    # (см. _check_direction_and_group), группу/направление сам импорт не
    # создаёт (не на чём: не хватает филиала, преподавателя и т.д. — это
    # за пределами этого тикета).
    direction_name: str = ""
    group_name: str = ""
    errors: list[str] = field(default_factory=list)
    # Не блокируют строку — слабое совпадение по ФИО, дубль (пропуск —
    # не поломка данных), несуществующее направление/группа.
    warnings: list[str] = field(default_factory=list)

    # Заполняется resolve_rows() — не на этапе разбора файла.
    action: str = RowAction.CREATE_NEW_FAMILY
    reason: str | None = None  # DuplicateReason.* — почему предложено именно это действие
    matched_child: Child | None = None
    matched_parent_id: str | None = None
    # Объект (не только id) — только для отрисовки предпросмотра, не
    # сериализуется в rows_json (после подтверждения ChildService сам
    # найдёт родителя по matched_parent_id).
    matched_parent: object | None = None
    # Номер строки файла, чья семья "усыновит" этого ребёнка — заполнен,
    # когда matched_parent_id ещё не существует в базе (родителя создаст
    # ЭТА строка при выполнении, см. execute_import): предпросмотру нечего
    # показать как id, но показать "строка N" — можно и нужно.
    attached_to_row_number: int | None = None

    @property
    def is_valid(self) -> bool:
        return not self.errors

    @property
    def role_label(self) -> str:
        try:
            return ChildContact.Role(self.role).label
        except ValueError:
            return self.role

    @property
    def gender_label(self) -> str:
        try:
            return Child.Gender(self.gender).label
        except ValueError:
            return self.gender

    def to_dict(self) -> dict:
        """Для передачи между шагами (скрытое поле формы / ImportJob.rows_payload)
        — только примитивы, не сами объекты Child/ParentContact
        (matched_child/matched_parent восстанавливать не нужно: к моменту
        сериализации решение уже принято, дальше нужен только id)."""
        return {
            "row_number": self.row_number,
            "child_name": self.child_name,
            "birth_date": self.birth_date.isoformat() if self.birth_date else None,
            "gender": self.gender,
            "parent_name": self.parent_name,
            "phone": self.phone,
            "extra_phones": self.extra_phones,
            "role": self.role,
            "medical_notes": self.medical_notes,
            "reported_balance": self.reported_balance,
            "direction_name": self.direction_name,
            "group_name": self.group_name,
            "errors": self.errors,
            "warnings": self.warnings,
            "action": self.action,
            "matched_parent_id": self.matched_parent_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ImportRow":
        return cls(
            row_number=data["row_number"],
            child_name=data.get("child_name", ""),
            birth_date=(
                datetime.date.fromisoformat(data["birth_date"]) if data.get("birth_date") else None
            ),
            gender=data.get("gender", ""),
            parent_name=data.get("parent_name", ""),
            phone=data.get("phone", ""),
            extra_phones=data.get("extra_phones") or [],
            role=data.get("role", ChildContact.Role.OTHER),
            medical_notes=data.get("medical_notes", ""),
            reported_balance=data.get("reported_balance", ""),
            direction_name=data.get("direction_name", ""),
            group_name=data.get("group_name", ""),
            errors=data.get("errors") or [],
            warnings=data.get("warnings") or [],
            action=data.get("action", RowAction.CREATE_NEW_FAMILY),
            matched_parent_id=data.get("matched_parent_id"),
        )


# Три формата дат из реальной практики (ТЗ): точки, слэши, ISO — плюс
# нативная дата Excel (обрабатывается отдельно ниже, это не строка).
_DATE_FORMATS = ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d")


def _parse_cell_date(value):
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str) and value.strip():
        for fmt in _DATE_FORMATS:
            try:
                return datetime.datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
    return None


def _clean_str(value) -> str:
    return str(value).strip() if value is not None else ""


# "Правдоподобна" (ТЗ, тикет про сухой прогон) — не только разобралась, но
# и не выглядит как опечатка вида "1905" вместо "2005" (тот самый пример из
# тикета). 100 лет — заведомо шире любого реального возраста ребёнка в
# кружке/секции, так что не даёт ложных срабатываний на настоящих данных,
# но ловит именно такие перепутанные цифры года.
_MAX_PLAUSIBLE_AGE_YEARS = 100


def _birth_date_plausibility_error(birth_date: datetime.date) -> str | None:
    today = datetime.date.today()
    if birth_date > today:
        return f"дата рождения в будущем: {birth_date.strftime('%d.%m.%Y')}"
    if birth_date.year <= today.year - _MAX_PLAUSIBLE_AGE_YEARS:
        return (
            f"дата рождения невероятно старая, похоже на опечатку в годе: "
            f"{birth_date.strftime('%d.%m.%Y')}"
        )
    return None


def build_row(
    row_number: int,
    values: dict,
    known_direction_names: frozenset[str] = frozenset(),
    known_group_names: frozenset[str] = frozenset(),
) -> ImportRow:
    """Строка после маппинга (column_mapping.apply_mapping) → очищенный
    ImportRow с ошибками/предупреждениями валидации. `values` —
    {ключ_поля: сырое_значение из файла}, ключ отсутствует или None, если
    поле не сопоставлено с колонкой (для необязательных полей это
    нормально). known_direction_names/known_group_names — уже
    существующие в организации названия (в нижнем регистре, без пробелов
    по краям) — передаются один раз на весь файл (не запрос в базу на
    каждую строку), см. tasks.run_dry_run_job."""
    row = ImportRow(row_number=row_number)
    errors = []
    warnings = []

    row.child_name = _clean_str(values.get("child_name"))
    if not row.child_name:
        errors.append("не заполнено ФИО ребёнка")

    birth_date = _parse_cell_date(values.get("birth_date"))
    if birth_date is None:
        errors.append("не удалось разобрать дату рождения (ожидается ДД.ММ.ГГГГ)")
    else:
        plausibility_error = _birth_date_plausibility_error(birth_date)
        if plausibility_error:
            errors.append(plausibility_error)
    row.birth_date = birth_date

    gender_raw = _clean_str(values.get("gender"))
    gender = GENDER_ALIASES.get(gender_raw.lower())
    # Сообщения — для администратора без ИТ-подготовки (ТЗ п. 10.4):
    # значение как есть, без кавычек-repr, и отдельный текст для пустой ячейки.
    if gender is None:
        if gender_raw:
            errors.append(f"не удалось разобрать пол ребёнка: {gender_raw} (ожидается м/ж)")
        else:
            errors.append("не указан пол ребёнка")
    row.gender = gender or ""

    parent_name_raw = _clean_str(values.get("parent_name"))
    prefix_role, cleaned_parent_name = _split_role_prefix(parent_name_raw)
    row.parent_name = cleaned_parent_name
    if not row.parent_name:
        errors.append("не заполнено ФИО родителя")

    phone_raw = _clean_str(values.get("phone"))
    normalized_phones = []
    for candidate in _split_phones(phone_raw):
        try:
            normalized = normalize_phone_number(candidate)
        except InvalidPhoneNumberError:
            continue
        if normalized not in normalized_phones:
            normalized_phones.append(normalized)
    if not normalized_phones:
        if phone_raw:
            errors.append(f"не удалось разобрать телефон: {phone_raw}")
        else:
            errors.append("не заполнен телефон")
        row.phone = phone_raw
    else:
        row.phone = normalized_phones[0]
        row.extra_phones = normalized_phones[1:]

    # Явная колонка "Роль родителя" приоритетнее роли, угаданной из
    # префикса в имени ("мама Айгерим") — администратор мог заполнить
    # обе, и явная колонка — более осознанный ввод.
    role_raw = _clean_str(values.get("role")).lower()
    row.role = ROLE_ALIASES.get(role_raw) or prefix_role or ChildContact.Role.OTHER

    row.medical_notes = _clean_str(values.get("medical_notes"))
    row.reported_balance = _clean_str(values.get("reported_balance"))

    row.direction_name = _clean_str(values.get("direction"))
    if row.direction_name and row.direction_name.lower() not in known_direction_names:
        warnings.append(
            f"направление «{row.direction_name}» не найдено — при импорте не создаётся "
            "автоматически, заведите его в справочнике направлений"
        )

    row.group_name = _clean_str(values.get("group"))
    if row.group_name and row.group_name.lower() not in known_group_names:
        warnings.append(
            f"группа «{row.group_name}» не найдена — при импорте не создаётся автоматически, "
            "заведите её и добавьте ребёнка вручную"
        )

    row.errors = errors
    row.warnings = warnings
    return row


def build_rows(
    mapped_rows: list[tuple[int, dict]],
    known_direction_names: frozenset[str] = frozenset(),
    known_group_names: frozenset[str] = frozenset(),
) -> list[ImportRow]:
    return [
        build_row(row_number, values, known_direction_names, known_group_names)
        for row_number, values in mapped_rows
    ]


class _PhoneResolutionMap:
    """Телефон -> уже найденный/созданный родитель в рамках ОДНОГО прогона
    (предпросмотра или выполнения) — второй ребёнок с тем же номером
    внутри файла попадает к тому же родителю, а не заводит второго."""

    def __init__(self):
        self._by_phone: dict[str, dict] = {}

    def get(self, phone):
        return self._by_phone.get(phone)

    def remember(self, phone, *, parent_id, row_number, child_keys=()):
        entry = self._by_phone.setdefault(
            phone, {"parent_id": parent_id, "row_number": row_number, "children": set()}
        )
        entry["parent_id"] = parent_id
        entry["row_number"] = row_number
        entry["children"].update(child_keys)

    @staticmethod
    def child_key(child_name, birth_date):
        return (child_name.lower(), birth_date)


def resolve_rows(organization, rows: list[ImportRow]) -> None:
    """Проставляет action/reason/matched_* на каждой валидной строке —
    дедуп и внутри файла, и против базы (см. докстринг модуля). Строки с
    ошибками разбора не резолвятся вообще (action не имеет смысла)."""
    phone_map = _PhoneResolutionMap()

    for row in rows:
        if not row.is_valid:
            row.action = RowAction.ERROR
            continue

        remembered = phone_map.get(row.phone)
        if remembered:
            child_key = _PhoneResolutionMap.child_key(row.child_name, row.birth_date)
            if child_key in remembered["children"]:
                # Тот же телефон И тот же ребёнок, что уже встречались в
                # этом файле — повтор строки, не второй ребёнок.
                row.action = RowAction.SKIP
                row.reason = DuplicateReason.PHONE
                row.warnings.append(
                    f"дубликат внутри файла — такая же строка уже была в строке "
                    f"{remembered['row_number']}, при импорте будет пропущена"
                )
            else:
                row.action = RowAction.ATTACH_EXISTING
                row.reason = DuplicateReason.EXISTING_PARENT_NEW_CHILD
                row.matched_parent_id = remembered["parent_id"]
                if remembered["parent_id"] is None:
                    row.attached_to_row_number = remembered["row_number"]
                phone_map.remember(
                    row.phone,
                    parent_id=remembered["parent_id"],
                    row_number=remembered["row_number"],
                    child_keys=[child_key],
                )
            continue

        matches = ChildService.find_duplicates(
            organization,
            phone=row.phone,
            child_name=row.child_name,
            birth_date=row.birth_date,
        )
        phone_match = next((m for m in matches if m.reason == DuplicateReason.PHONE), None)
        family_match = next(
            (m for m in matches if m.reason == DuplicateReason.EXISTING_PARENT_NEW_CHILD), None
        )
        weak_match = next(
            (
                m
                for m in matches
                if m.reason in (DuplicateReason.NAME_AND_BIRTH_DATE, DuplicateReason.NAME_ONLY)
            ),
            None,
        )

        if phone_match:
            # Тот же телефон И тот же ребёнок — похоже на повтор строки/
            # повторную загрузку того же файла. По умолчанию пропускаем,
            # администратор может явно выбрать "создать всё равно".
            row.action = RowAction.SKIP
            row.reason = DuplicateReason.PHONE
            row.matched_child = phone_match.child
            row.warnings.append(
                f"дубликат — такой ребёнок уже есть в базе "
                f"({phone_match.child.full_name}, {phone_match.child.birth_date:%d.%m.%Y}), "
                "при импорте будет пропущена"
            )
        elif family_match:
            row.action = RowAction.ATTACH_EXISTING
            row.reason = DuplicateReason.EXISTING_PARENT_NEW_CHILD
            row.matched_parent_id = str(family_match.parent.id)
            row.matched_parent = family_match.parent
            existing_keys = _existing_family_child_keys(organization, row.phone)
            existing_keys.add(_PhoneResolutionMap.child_key(row.child_name, row.birth_date))
            phone_map.remember(
                row.phone,
                parent_id=row.matched_parent_id,
                row_number=row.row_number,
                child_keys=existing_keys,
            )
        else:
            row.action = RowAction.CREATE_NEW_FAMILY
            if weak_match:
                # Слабый сигнал — показать, но не настаивать (ТЗ): не
                # блокирует и не меняет действие по умолчанию.
                row.reason = weak_match.reason
                row.matched_child = weak_match.child
                row.warnings.append(
                    f"похоже на уже существующего ребёнка "
                    f"({weak_match.child.full_name}, {weak_match.child.birth_date:%d.%m.%Y}), "
                    "но совпадения недостаточно для автоматической привязки — будет создана "
                    "новая запись, проверьте вручную"
                )
            phone_map.remember(
                row.phone,
                parent_id=None,
                row_number=row.row_number,
                child_keys=[_PhoneResolutionMap.child_key(row.child_name, row.birth_date)],
            )


class ReportLevel:
    READY = "ready"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class DryRunReport:
    ready_count: int = 0
    warning_count: int = 0
    error_count: int = 0
    # [{row_number, level, child_name, messages}, ...] — по номеру строки
    # исходного файла (не внутреннему индексу, ТЗ п. 10.4), используется и
    # для экрана отчёта, и для выгрузки файлом (см. reporting.py).
    rows: list[dict] = field(default_factory=list)


def build_dry_run_report(rows: list[ImportRow]) -> DryRunReport:
    """Классифицирует каждую строку в готова/предупреждение/ошибка — не
    пишет в базу (сухой прогон, ТЗ п. 4.1): вызывается ПОСЛЕ resolve_rows,
    но никогда execute_import."""
    report = DryRunReport()
    for row in rows:
        if not row.is_valid:
            level = ReportLevel.ERROR
            messages = row.errors
            report.error_count += 1
        elif row.warnings:
            level = ReportLevel.WARNING
            messages = row.warnings
            report.warning_count += 1
        else:
            level = ReportLevel.READY
            messages = []
            report.ready_count += 1
        report.rows.append(
            {
                "row_number": row.row_number,
                "level": level,
                "child_name": row.child_name,
                "messages": messages,
            }
        )
    return report


@dataclass
class ImportResult:
    created: int = 0
    attached_to_existing_family: int = 0
    skipped: int = 0
    failed: list[tuple[int, str]] = field(default_factory=list)  # (row_number, error)
    # Строки, где была непустая колонка "Остаток занятий" — сознательно
    # НЕ превращается в реальный Subscription при импорте (см.
    # docs/import_format.md), но и не пропадает молча: администратор
    # должен увидеть и перенести остаток вручную/отдельным механизмом.
    unhandled_balances: list[tuple[int, str, str]] = field(
        default_factory=list
    )  # (row_number, child_name, reported_balance)


def execute_import(organization, rows: list[ImportRow]) -> ImportResult:
    """Строки — по порядку файла (важно для второго ребёнка в семье в
    рамках одного прогона, см. _PhoneResolutionMap)."""
    result = ImportResult()
    phone_map = _PhoneResolutionMap()

    for row in rows:
        if row.reported_balance and row.action not in (RowAction.SKIP, RowAction.ERROR):
            result.unhandled_balances.append((row.row_number, row.child_name, row.reported_balance))

        if row.action in (RowAction.SKIP, RowAction.ERROR):
            result.skipped += 1
            continue

        try:
            child_data = {
                "full_name": row.child_name,
                "birth_date": row.birth_date,
                "gender": row.gender,
                "medical_notes": row.medical_notes,
            }

            remembered = phone_map.get(row.phone)
            if remembered:
                parent_data = {"id": remembered["parent_id"]}
            elif row.action == RowAction.ATTACH_EXISTING and row.matched_parent_id:
                parent_data = {"id": row.matched_parent_id}
            else:
                parent_data = {
                    "full_name": row.parent_name,
                    "phones": [row.phone, *row.extra_phones],
                }

            child = ChildService.create_with_parent(
                organization, child_data=child_data, parent_data=parent_data, link_role=row.role
            )
            parent_id = str(ChildContact.objects.get(child=child).parent_contact_id)
            phone_map.remember(row.phone, parent_id=parent_id, row_number=row.row_number)

            if row.action == RowAction.ATTACH_EXISTING:
                result.attached_to_existing_family += 1
            else:
                result.created += 1
        except Exception as exc:  # noqa: BLE001 — одна плохая строка не должна ронять весь импорт
            result.failed.append((row.row_number, str(exc)))

    return result
