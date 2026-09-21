"""
Импорт детей из Excel (ТЗ п. 4.1, MVP критерий приёмки №1: "дубли
выявлены при импорте") — первый из трёх потребителей ChildService
(services.py, TRU-8 контракт №2). Не своя копия поиска дублей — весь
дедуп идёт через ChildService.find_duplicates(), иначе этот экран и
будущая конвертация заявки (M2) посчитают дубли по-разному.

Формат файла — фиксированные колонки (см. EXPECTED_HEADERS), без
произвольного сопоставления: администратору проще один раз привести файл
к формату, чем каждый раз сопоставлять колонки вручную, а сопоставление
"на глаз" само может стать источником ошибок импорта.

Дедуп внутри файла и второй ребёнок в семье внутри ОДНОГО файла — тот же
сценарий из ТЗ ("тот же телефон, другой ребёнок"), просто оба ребёнка
приходят в одном файле, а не по одному через веб-форму: строки
обрабатываются по порядку, и телефон, once встреченный, "запоминается"
на время предпросмотра/выполнения (см. _PhoneResolutionMap) — второй
ребёнок в файле с тем же номером не создаёт вторую маму.
"""

import datetime
from dataclasses import dataclass, field

import openpyxl
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


# Порядок значим только для сообщения об ошибке заголовка — сами колонки
# ищутся по названию, не по позиции (администратор может переставить
# столбцы местами в своей копии файла).
EXPECTED_HEADERS = {
    "ФИО ребёнка": "child_name",
    "Дата рождения ребёнка": "birth_date",
    "Пол ребёнка": "gender",
    "ФИО родителя": "parent_name",
    "Телефон родителя": "phone",
    "Роль родителя": "role",
}
REQUIRED_HEADERS = [h for h in EXPECTED_HEADERS if h != "Роль родителя"]

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
    phone: str = ""
    role: str = ChildContact.Role.OTHER
    errors: list[str] = field(default_factory=list)

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


def _parse_cell_date(value):
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str) and value.strip():
        for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
            try:
                return datetime.datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
    return None


def _clean_str(value) -> str:
    return str(value).strip() if value is not None else ""


def parse_workbook(file) -> tuple[list[ImportRow], list[str]]:
    """
    Возвращает (строки, ошибки_заголовка). При ошибке заголовка строки
    пустые — нет смысла разбирать данные под неверными колонками.
    """
    workbook = openpyxl.load_workbook(file, data_only=True, read_only=True)
    sheet = workbook.active

    header_row = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), ())
    header_index = {
        _clean_str(cell): idx for idx, cell in enumerate(header_row) if _clean_str(cell)
    }
    missing = [h for h in REQUIRED_HEADERS if h not in header_index]
    if missing:
        return [], [f"В файле не найдены обязательные колонки: {', '.join(missing)}"]

    rows = []
    for row_number, raw_row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
        if not any(_clean_str(v) for v in raw_row):
            continue  # пустая строка — обычный хвост файла, не ошибка

        def cell(header, _raw_row=raw_row):
            idx = header_index.get(header)
            return _raw_row[idx] if idx is not None and idx < len(_raw_row) else None

        row = ImportRow(row_number=row_number)
        errors = []

        row.child_name = _clean_str(cell("ФИО ребёнка"))
        if not row.child_name:
            errors.append("не заполнено ФИО ребёнка")

        birth_date = _parse_cell_date(cell("Дата рождения ребёнка"))
        if birth_date is None:
            errors.append("не удалось разобрать дату рождения (ожидается ДД.МM.ГГГГ)")
        row.birth_date = birth_date

        gender_raw = _clean_str(cell("Пол ребёнка")).lower()
        gender = GENDER_ALIASES.get(gender_raw)
        if gender is None:
            errors.append(f"не удалось разобрать пол ребёнка: {gender_raw!r}")
        row.gender = gender or ""

        row.parent_name = _clean_str(cell("ФИО родителя"))
        if not row.parent_name:
            errors.append("не заполнено ФИО родителя")

        phone_raw = _clean_str(cell("Телефон родителя"))
        try:
            row.phone = normalize_phone_number(phone_raw)
        except InvalidPhoneNumberError:
            errors.append(f"не похоже на телефон: {phone_raw!r}")
            row.phone = phone_raw

        role_raw = _clean_str(cell("Роль родителя")).lower()
        row.role = ROLE_ALIASES.get(role_raw, ChildContact.Role.OTHER)

        row.errors = errors
        rows.append(row)

    return rows, []


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
            phone_map.remember(
                row.phone,
                parent_id=None,
                row_number=row.row_number,
                child_keys=[_PhoneResolutionMap.child_key(row.child_name, row.birth_date)],
            )


@dataclass
class ImportResult:
    created: int = 0
    attached_to_existing_family: int = 0
    skipped: int = 0
    failed: list[tuple[int, str]] = field(default_factory=list)  # (row_number, error)


def execute_import(organization, rows: list[ImportRow]) -> ImportResult:
    """Строки — по порядку файла (важно для второго ребёнка в семье в
    рамках одного прогона, см. _PhoneResolutionMap)."""
    result = ImportResult()
    phone_map = _PhoneResolutionMap()

    for row in rows:
        if row.action in (RowAction.SKIP, RowAction.ERROR):
            result.skipped += 1
            continue

        try:
            child_data = {
                "full_name": row.child_name,
                "birth_date": row.birth_date,
                "gender": row.gender,
            }

            remembered = phone_map.get(row.phone)
            if remembered:
                parent_data = {"id": remembered["parent_id"]}
            elif row.action == RowAction.ATTACH_EXISTING and row.matched_parent_id:
                parent_data = {"id": row.matched_parent_id}
            else:
                parent_data = {"full_name": row.parent_name, "phones": [row.phone]}

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
