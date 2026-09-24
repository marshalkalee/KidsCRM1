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

Запись (тикет «запись данных с разрешением дублей»): по каждому
совпадению (DuplicateKind) администратор выбирает «создать нового» /
«привязать к существующему» / «пропустить», в том числе сразу для всех
однотипных (apply_decisions). execute_import пишет одной транзакцией —
целиком или ничего; всё созданное запоминается, чтобы импорт можно было
откатить (rollback_import), пока с данными не начали работать.
"""

import datetime
import re
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from domains.platform.core.audit import AuditLog
from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number

from .models import Child, ChildContact, CommunicationLog, ContactPhone, ImportJob, ParentContact
from .services import ChildService, DuplicateReason

# Как часто (в строках) сообщать о прогрессе — на 5000 строк это ~100
# обновлений: экран не выглядит зависшим, а кэш не заваливается записями.
PROGRESS_EVERY = 50


def _existing_family_children(organization, phone) -> dict:
    """{(имя.lower(), дата рождения): child_id} уже существующих детей всех
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
    return {(c.full_name.lower(), c.birth_date): str(c.id) for c in children}


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
    ATTACH_EXISTING = "attach_existing"  # новый ребёнок к существующему родителю
    ATTACH_TO_CHILD = "attach_to_child"  # не новый ребёнок — уже существующий
    SKIP = "skip"
    ERROR = "error"


class DuplicateKind:
    """Вид найденного совпадения — по нему группируются решения
    администратора (массовое решение «для всех однотипных», ТЗ п. 4.1)."""

    IN_FILE = "in_file"  # тот же ребёнок с тем же телефоном выше в этом же файле
    EXACT = "exact"  # тот же ребёнок с тем же телефоном уже есть в базе
    FAMILY = "family"  # телефон родителя уже есть в базе, ребёнок — новый
    WEAK = "weak"  # совпало только ФИО (или ФИО + дата рождения), телефон другой


DUPLICATE_KIND_LABELS = {
    DuplicateKind.IN_FILE: "Повтор внутри файла",
    DuplicateKind.EXACT: "Ребёнок уже есть в базе",
    DuplicateKind.FAMILY: "Родитель уже есть в базе",
    DuplicateKind.WEAK: "Похожий ребёнок в базе",
}


class Decision:
    CREATE_NEW = "create_new"
    ATTACH = "attach"
    SKIP = "skip"


# Первый вариант — действие по умолчанию (то, что resolve_rows выбирает сам).
DECISION_OPTIONS = {
    DuplicateKind.IN_FILE: [Decision.SKIP, Decision.ATTACH, Decision.CREATE_NEW],
    DuplicateKind.EXACT: [Decision.SKIP, Decision.ATTACH, Decision.CREATE_NEW],
    DuplicateKind.FAMILY: [Decision.ATTACH, Decision.CREATE_NEW, Decision.SKIP],
    DuplicateKind.WEAK: [Decision.CREATE_NEW, Decision.ATTACH, Decision.SKIP],
}

# «Привязать к существующему» значит разное: для FAMILY — новый ребёнок к
# уже существующему родителю, для остальных — это тот же ребёнок (новый не
# создаётся; дописываются контакт из файла, группа, направление).
DECISION_LABELS = {
    DuplicateKind.IN_FILE: {
        Decision.SKIP: "Пропустить строку",
        Decision.ATTACH: "Тот же ребёнок — дописать группу/направление",
        Decision.CREATE_NEW: "Создать ещё одного ребёнка",
    },
    DuplicateKind.EXACT: {
        Decision.SKIP: "Пропустить строку",
        Decision.ATTACH: "Тот же ребёнок — дописать группу/направление",
        Decision.CREATE_NEW: "Создать нового ребёнка",
    },
    DuplicateKind.FAMILY: {
        Decision.ATTACH: "Привязать к существующему родителю",
        Decision.CREATE_NEW: "Создать нового родителя",
        Decision.SKIP: "Пропустить строку",
    },
    DuplicateKind.WEAK: {
        Decision.CREATE_NEW: "Создать нового ребёнка",
        Decision.ATTACH: "Тот же ребёнок — привязать к существующему",
        Decision.SKIP: "Пропустить строку",
    },
}


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
    # Заполняется resolve_rows(): вид совпадения (DuplicateKind.*) — только у
    # строк, по которым администратор может принять решение.
    duplicate_kind: str | None = None
    matched_child_id: str | None = None
    # IN_FILE: строка файла, где этот ребёнок встретился впервые.
    matched_row_number: int | None = None
    # Решение администратора (Decision.*) — единственное из этих полей,
    # которое переживает сериализацию: всё остальное resolve_rows
    # пересчитывает при выполнении заново по текущему состоянию базы.
    decision: str | None = None
    # FAMILY + CREATE_NEW: новый родитель, хотя телефон уже есть в базе.
    force_new_parent: bool = False
    # С кем совпало — человекочитаемо, для экрана решений (не сериализуется).
    matched_label: str = ""

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
            "decision": self.decision,
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
            decision=data.get("decision"),
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


def _name_key(name: str) -> str:
    return " ".join(name.split()).lower()


@dataclass
class DirectoryLookup:
    """Направления и группы организации — загружаются один раз на весь файл
    (не запрос в базу на каждую строку, ТЗ п. 10.1).

    Решение по тикету «запись данных с разрешением дублей»: импорт НЕ
    создаёт ни направления, ни группы — только находит уже заведённые
    (группе нужны филиал, вместимость, преподаватель — из файла их не
    взять, а автосоздание на грязных данных плодит «Балет»/«балет »/«Балет
    5-7»). Сравнение — без учёта регистра и лишних пробелов. Подробнее —
    docs/import_format.md."""

    # имя (см. _name_key) -> [direction_id, ...]
    directions: dict[str, list[str]] = field(default_factory=dict)
    # имя группы -> [(group_id, direction_id, имя направления), ...]
    groups: dict[str, list[tuple[str, str, str]]] = field(default_factory=dict)

    @classmethod
    def load(cls, organization) -> "DirectoryLookup":
        # Локальный импорт — clients не держит постоянную зависимость от
        # домена Дарьи (groups) на уровне модуля.
        from domains.platform.tenants.models import Direction
        from domains.scheduling.groups.models import Group

        lookup = cls()
        for direction in Direction.objects.for_tenant(organization):
            lookup.directions.setdefault(_name_key(direction.name), []).append(str(direction.id))
        groups = (
            Group.objects.for_tenant(organization)
            .exclude(status=Group.Status.CLOSED)
            .select_related("direction")
        )
        for group in groups:
            lookup.groups.setdefault(_name_key(group.name), []).append(
                (str(group.id), str(group.direction_id), _name_key(group.direction.name))
            )
        return lookup

    def find_direction(self, name: str) -> tuple[str | None, str | None]:
        """(direction_id, None) или (None, текст предупреждения)."""
        found = self.directions.get(_name_key(name), [])
        if len(found) == 1:
            return found[0], None
        if not found:
            return None, (
                f"направление «{name}» не найдено — импорт направления не создаёт, "
                "ребёнок будет импортирован без него; заведите направление заранее"
            )
        return None, (
            f"найдено несколько направлений «{name}» — ребёнок будет импортирован "
            "без направления; переименуйте повторяющиеся направления"
        )

    def find_group(
        self, name: str, direction_name: str = ""
    ) -> tuple[tuple[str, str] | None, str | None]:
        """((group_id, direction_id), None) или (None, текст предупреждения).
        Направление из той же строки сужает выбор, если групп с таким
        названием несколько (например, «Младшая» в балете и в пении)."""
        found = self.groups.get(_name_key(name), [])
        if direction_name and len(found) > 1:
            found = [g for g in found if g[2] == _name_key(direction_name)]
        if len(found) == 1:
            group_id, direction_id, _ = found[0]
            return (group_id, direction_id), None
        if not found:
            return None, (
                f"группа «{name}» не найдена — импорт групп не создаёт, ребёнок будет "
                "импортирован без группы; заведите группу заранее и запустите сухой "
                "прогон заново"
            )
        return None, (
            f"найдено несколько групп «{name}» — ребёнок будет импортирован без группы; "
            "укажите направление в колонке «Направление» или переименуйте группы"
        )


def build_row(
    row_number: int,
    values: dict,
    lookup: DirectoryLookup | None = None,
) -> ImportRow:
    """Строка после маппинга (column_mapping.apply_mapping) → очищенный
    ImportRow с ошибками/предупреждениями валидации. `values` —
    {ключ_поля: сырое_значение из файла}, ключ отсутствует или None, если
    поле не сопоставлено с колонкой (для необязательных полей это
    нормально). `lookup` — справочник направлений/групп организации,
    загружается один раз на весь файл (DirectoryLookup.load)."""
    lookup = lookup or DirectoryLookup()
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
    if row.direction_name:
        _, problem = lookup.find_direction(row.direction_name)
        if problem:
            warnings.append(problem)

    row.group_name = _clean_str(values.get("group"))
    if row.group_name:
        _, problem = lookup.find_group(row.group_name, row.direction_name)
        if problem:
            warnings.append(problem)

    row.errors = errors
    row.warnings = warnings
    return row


def build_rows(
    mapped_rows: list[tuple[int, dict]], lookup: DirectoryLookup | None = None
) -> list[ImportRow]:
    lookup = lookup or DirectoryLookup()
    return [build_row(row_number, values, lookup) for row_number, values in mapped_rows]


class _PhoneResolutionMap:
    """Телефон -> уже найденный/созданный родитель в рамках ОДНОГО прогона
    предпросмотра — второй ребёнок с тем же номером внутри файла попадает
    к тому же родителю, а не заводит второго.

    `children` — дети этой семьи: {child_key: {"row_number", "child_id"}}.
    row_number=None — ребёнок уже был в базе; child_id=None — появится
    только при выполнении (его создаст строка row_number).
    `db_parent_label` — имя родителя, если он найден в БАЗЕ (а не будет
    создан этим файлом): следующие дети с тем же телефоном — тоже
    совпадение FAMILY, по которому решает администратор."""

    def __init__(self):
        self._by_phone: dict[str, dict] = {}

    def get(self, phone):
        return self._by_phone.get(phone)

    def remember(self, phone, *, parent_id, row_number, children=None, db_parent_label=None):
        entry = self._by_phone.setdefault(
            phone, {"parent_id": parent_id, "row_number": row_number, "children": {}}
        )
        entry["parent_id"] = parent_id
        entry["row_number"] = row_number
        if db_parent_label:
            entry["db_parent_label"] = db_parent_label
        for key, origin in (children or {}).items():
            entry["children"].setdefault(key, origin)

    @staticmethod
    def child_key(child_name, birth_date):
        return (child_name.lower(), birth_date)


def _db_children(existing: dict) -> dict:
    return {key: {"row_number": None, "child_id": child_id} for key, child_id in existing.items()}


def _child_label(child) -> str:
    return f"{child.full_name}, {child.birth_date:%d.%m.%Y}"


def resolve_rows(organization, rows: list[ImportRow], on_progress=None) -> None:
    """Проставляет action/reason/duplicate_kind/matched_* на каждой валидной
    строке — дедуп и внутри файла, и против базы (см. докстринг модуля).
    Строки с ошибками разбора не резолвятся вообще (action не имеет
    смысла). Действие здесь — по умолчанию; решение администратора
    накладывается поверх (apply_decisions)."""
    phone_map = _PhoneResolutionMap()
    total = len(rows)

    for index, row in enumerate(rows, start=1):
        if on_progress and (index % PROGRESS_EVERY == 0 or index == total):
            on_progress(index, total)

        if not row.is_valid:
            row.action = RowAction.ERROR
            continue

        child_key = _PhoneResolutionMap.child_key(row.child_name, row.birth_date)
        remembered = phone_map.get(row.phone)
        if remembered:
            origin = remembered["children"].get(child_key)
            if origin:
                # Тот же телефон И тот же ребёнок, что уже встречались —
                # повтор, не второй ребёнок.
                row.action = RowAction.SKIP
                row.reason = DuplicateReason.PHONE
                row.matched_parent_id = remembered["parent_id"]
                if origin["row_number"] is not None:
                    row.duplicate_kind = DuplicateKind.IN_FILE
                    row.matched_row_number = origin["row_number"]
                    row.matched_label = f"строка {origin['row_number']}"
                    row.warnings.append(
                        f"дубликат внутри файла — этот ребёнок уже был в строке "
                        f"{origin['row_number']}, по умолчанию строка будет пропущена"
                    )
                else:
                    row.duplicate_kind = DuplicateKind.EXACT
                    row.matched_child_id = origin["child_id"]
                    child = Child.objects.for_tenant(organization).get(pk=origin["child_id"])
                    row.matched_label = _child_label(child)
                    row.warnings.append(
                        f"дубликат — такой ребёнок уже есть в базе ({row.matched_label}), "
                        "по умолчанию строка будет пропущена"
                    )
            else:
                row.action = RowAction.ATTACH_EXISTING
                row.reason = DuplicateReason.EXISTING_PARENT_NEW_CHILD
                row.matched_parent_id = remembered["parent_id"]
                if remembered["parent_id"] is None:
                    row.attached_to_row_number = remembered["row_number"]
                if remembered.get("db_parent_label"):
                    row.duplicate_kind = DuplicateKind.FAMILY
                    row.matched_label = remembered["db_parent_label"]
                phone_map.remember(
                    row.phone,
                    parent_id=remembered["parent_id"],
                    row_number=remembered["row_number"],
                    children={child_key: {"row_number": row.row_number, "child_id": None}},
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
            # администратор может решить иначе (apply_decisions).
            row.action = RowAction.SKIP
            row.reason = DuplicateReason.PHONE
            row.duplicate_kind = DuplicateKind.EXACT
            row.matched_child = phone_match.child
            row.matched_child_id = str(phone_match.child.id)
            row.matched_parent_id = str(phone_match.parent.id)
            row.matched_label = _child_label(phone_match.child)
            row.warnings.append(
                f"дубликат — такой ребёнок уже есть в базе ({row.matched_label}), "
                "по умолчанию строка будет пропущена"
            )
            phone_map.remember(
                row.phone,
                parent_id=row.matched_parent_id,
                row_number=row.row_number,
                children=_db_children(_existing_family_children(organization, row.phone)),
                db_parent_label=phone_match.parent.full_name,
            )
        elif family_match:
            row.action = RowAction.ATTACH_EXISTING
            row.reason = DuplicateReason.EXISTING_PARENT_NEW_CHILD
            row.duplicate_kind = DuplicateKind.FAMILY
            row.matched_parent_id = str(family_match.parent.id)
            row.matched_parent = family_match.parent
            row.matched_label = family_match.parent.full_name
            children = _db_children(_existing_family_children(organization, row.phone))
            children.setdefault(child_key, {"row_number": row.row_number, "child_id": None})
            phone_map.remember(
                row.phone,
                parent_id=row.matched_parent_id,
                row_number=row.row_number,
                children=children,
                db_parent_label=family_match.parent.full_name,
            )
        else:
            row.action = RowAction.CREATE_NEW_FAMILY
            if weak_match:
                # Слабый сигнал — показать, но не настаивать (ТЗ): не
                # блокирует и не меняет действие по умолчанию.
                row.reason = weak_match.reason
                row.duplicate_kind = DuplicateKind.WEAK
                row.matched_child = weak_match.child
                row.matched_child_id = str(weak_match.child.id)
                row.matched_label = _child_label(weak_match.child)
                row.warnings.append(
                    f"похоже на уже существующего ребёнка ({row.matched_label}), "
                    "но совпадения недостаточно для автоматической привязки — по умолчанию "
                    "будет создана новая запись, проверьте вручную"
                )
            phone_map.remember(
                row.phone,
                parent_id=None,
                row_number=row.row_number,
                children={child_key: {"row_number": row.row_number, "child_id": None}},
            )


def apply_decisions(rows: list[ImportRow]) -> None:
    """Решение администратора по дублю (row.decision) поверх действия по
    умолчанию из resolve_rows. Решение, неприменимое к виду совпадения
    (например, совпадение исчезло между сухим прогоном и выполнением), —
    игнорируется: остаётся действие по умолчанию."""
    for row in rows:
        kind = row.duplicate_kind
        if not kind or row.decision not in DECISION_OPTIONS[kind]:
            continue
        if row.decision == Decision.SKIP:
            row.action = RowAction.SKIP
        elif row.decision == Decision.ATTACH:
            row.action = (
                RowAction.ATTACH_EXISTING
                if kind == DuplicateKind.FAMILY
                else RowAction.ATTACH_TO_CHILD
            )
        elif kind == DuplicateKind.FAMILY:
            row.action = RowAction.CREATE_NEW_FAMILY
            row.force_new_parent = True
        elif kind in (DuplicateKind.EXACT, DuplicateKind.IN_FILE):
            # Ещё один ребёнок — но у того же родителя (телефон тот же),
            # не вторая мама с тем же номером.
            row.action = RowAction.ATTACH_EXISTING
        else:
            row.action = RowAction.CREATE_NEW_FAMILY


class ReportLevel:
    READY = "ready"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class DryRunReport:
    ready_count: int = 0
    warning_count: int = 0
    error_count: int = 0
    # [{row_number, level, child_name, messages, duplicate}, ...] — по
    # номеру строки исходного файла (не внутреннему индексу, ТЗ п. 10.4),
    # используется и для экрана отчёта, и для выгрузки файлом (см.
    # reporting.py). duplicate — None или {kind, matched, options}: строка,
    # по которой администратор принимает решение перед импортом.
    rows: list[dict] = field(default_factory=list)


def _duplicate_info(row: ImportRow) -> dict | None:
    if not row.is_valid or not row.duplicate_kind:
        return None
    return {
        "kind": row.duplicate_kind,
        "matched": row.matched_label,
        "options": DECISION_OPTIONS[row.duplicate_kind],
    }


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
                "duplicate": _duplicate_info(row),
            }
        )
    return report


CREATED_OBJECT_KEYS = (
    "children",
    "parents",
    "phones",
    "child_contacts",
    "group_memberships",
    "child_directions",  # [[child_id, direction_id], ...] — M2M, своего id нет
)


def _empty_created_objects() -> dict:
    return {key: [] for key in CREATED_OBJECT_KEYS}


@dataclass
class ImportResult:
    created: int = 0  # новый ребёнок + новый родитель
    attached_to_existing_family: int = 0  # новый ребёнок к уже существующему родителю
    linked_to_existing_child: int = 0  # строка привязана к уже существующему ребёнку
    parents_created: int = 0
    enrolled_in_groups: int = 0
    skipped: int = 0
    # Строки, не импортированные не из-за ошибки данных, а потому что
    # решение по дублю стало не к чему применить (см. _execute_row).
    failed: list[tuple[int, str]] = field(default_factory=list)  # (row_number, причина)
    # Строки, где была непустая колонка "Остаток занятий" — сознательно
    # НЕ превращается в реальный Subscription при импорте (см.
    # docs/import_format.md), но и не пропадает молча: администратор
    # должен увидеть и перенести остаток вручную/отдельным механизмом.
    unhandled_balances: list[tuple[int, str, str]] = field(
        default_factory=list
    )  # (row_number, child_name, reported_balance)
    # id всего созданного — для отката (rollback_import).
    created_objects: dict = field(default_factory=_empty_created_objects)


class ImportExecutionError(Exception):
    """Поломка на строке — весь импорт откатывается (execute_import
    транзакционен), а администратор видит номер строки файла."""

    def __init__(self, row_number: int, message: str):
        self.row_number = row_number
        super().__init__(f"строка {row_number}: {message}")


class _ExecutionState:
    def __init__(self, organization, lookup, result):
        self.organization = organization
        self.lookup = lookup
        self.result = result
        # Телефон -> родитель, найденный/созданный в ЭТОМ прогоне.
        self.parent_by_phone: dict[str, str] = {}
        # Номер строки -> ребёнок (новый или существующий) — для IN_FILE + ATTACH.
        self.child_by_row: dict[int, str] = {}
        self.today = timezone.localdate()


def _parent_data(row: ImportRow, state: _ExecutionState, *, prefer_existing: bool) -> dict:
    if prefer_existing:
        parent_id = row.matched_parent_id or state.parent_by_phone.get(row.phone)
        if parent_id:
            return {"id": parent_id}
    return {"full_name": row.parent_name, "phones": [row.phone, *row.extra_phones]}


def _record_new_parent(state: _ExecutionState, parent) -> None:
    created = state.result.created_objects
    created["parents"].append(str(parent.id))
    created["phones"].extend(str(pk) for pk in parent.phones.values_list("id", flat=True))
    state.result.parents_created += 1


def _enroll(state: _ExecutionState, child, row: ImportRow) -> None:
    """Существующие направление/группа из файла (DirectoryLookup) — ничего
    не создаётся, ненайденное уже показано предупреждением в сухом прогоне."""
    from domains.scheduling.groups.models import GroupMembership

    organization = state.organization
    created = state.result.created_objects
    direction_ids = []
    if row.direction_name:
        direction_id, _ = state.lookup.find_direction(row.direction_name)
        if direction_id:
            direction_ids.append(direction_id)
    if row.group_name:
        found, _ = state.lookup.find_group(row.group_name, row.direction_name)
        if found:
            group_id, group_direction_id = found
            already_in_group = (
                GroupMembership.objects.for_tenant(organization)
                .filter(group_id=group_id, child=child, left_at__isnull=True)
                .exists()
            )
            if not already_in_group:
                membership = GroupMembership.objects.create(
                    organization=organization,
                    group_id=group_id,
                    child=child,
                    joined_at=state.today,
                )
                created["group_memberships"].append(str(membership.id))
                state.result.enrolled_in_groups += 1
            direction_ids.append(group_direction_id)

    if direction_ids:
        existing = {str(pk) for pk in child.directions.values_list("id", flat=True)}
        for direction_id in dict.fromkeys(direction_ids):
            if direction_id not in existing:
                child.directions.add(direction_id)
                created["child_directions"].append([str(child.id), direction_id])


def _execute_row(state: _ExecutionState, row: ImportRow) -> None:
    organization = state.organization
    result = state.result
    created = result.created_objects

    if row.action in (RowAction.SKIP, RowAction.ERROR):
        result.skipped += 1
        return

    if row.action == RowAction.ATTACH_TO_CHILD:
        child_id = row.matched_child_id or state.child_by_row.get(row.matched_row_number)
        if not child_id:
            result.failed.append(
                (
                    row.row_number,
                    f"не к чему привязать — строка {row.matched_row_number} не импортирована",
                )
            )
            return
        child = Child.objects.for_tenant(organization).get(pk=child_id)
        parent_data = _parent_data(row, state, prefer_existing=True)
        link, parent, link_created = ChildService.link_parent(
            organization, child, parent_data=parent_data, link_role=row.role
        )
        if "id" not in parent_data:
            _record_new_parent(state, parent)
        if link_created:
            created["child_contacts"].append(str(link.id))
        result.linked_to_existing_child += 1
    else:
        parent_data = _parent_data(row, state, prefer_existing=not row.force_new_parent)
        child = ChildService.create_with_parent(
            organization,
            child_data={
                "full_name": row.child_name,
                "birth_date": row.birth_date,
                "gender": row.gender,
                "medical_notes": row.medical_notes,
            },
            parent_data=parent_data,
            link_role=row.role,
        )
        link = (
            ChildContact.objects.for_tenant(organization)
            .select_related("parent_contact")
            .get(child=child)
        )
        parent = link.parent_contact
        created["children"].append(str(child.id))
        created["child_contacts"].append(str(link.id))
        if "id" in parent_data:
            result.attached_to_existing_family += 1
        else:
            _record_new_parent(state, parent)
            result.created += 1

    state.parent_by_phone.setdefault(row.phone, str(parent.id))
    state.child_by_row[row.row_number] = str(child.id)
    if row.reported_balance:
        result.unhandled_balances.append((row.row_number, row.child_name, row.reported_balance))
    _enroll(state, child, row)


def execute_import(
    organization,
    rows: list[ImportRow],
    lookup: DirectoryLookup | None = None,
    on_progress=None,
) -> ImportResult:
    """Запись по результатам resolve_rows/apply_decisions. Строки — по
    порядку файла (важно для второго ребёнка в семье в рамках одного
    прогона).

    Транзакционно (тикет «запись данных с разрешением дублей»): импорт
    применяется целиком или не применяется вовсе — поломка на любой строке
    (или падение воркера посреди импорта) откатывает всё, частично
    заехавшей базы не бывает. Поэтому здесь нет try/except «пропустить
    строку и идти дальше»: плохая строка роняет весь импорт с её номером
    (ImportExecutionError). Ошибки данных сюда не доходят — их отсекает
    валидация (build_row), такие строки — RowAction.ERROR."""
    lookup = lookup or DirectoryLookup.load(organization)
    state = _ExecutionState(organization, lookup, ImportResult())
    total = len(rows)

    with transaction.atomic():
        for index, row in enumerate(rows, start=1):
            try:
                _execute_row(state, row)
            except ImportExecutionError:
                raise
            except Exception as exc:
                raise ImportExecutionError(row.row_number, str(exc)) from exc
            if on_progress and (index % PROGRESS_EVERY == 0 or index == total):
                on_progress(index, total)

    return state.result


# Аудит (ТЗ п. 2): отдельных действий «импорт»/«откат импорта» в
# AuditLog.Action пока нет (домен Bekzat'а) — пишем как создание/удаление
# записи ImportJob со сводкой в before/after. Когда в AuditLog появятся
# свои действия — поменять здесь, больше нигде.
IMPORT_AUDIT_ACTION = AuditLog.Action.CREATE
IMPORT_ROLLBACK_AUDIT_ACTION = AuditLog.Action.DELETE


def import_audit_summary(job: ImportJob) -> dict:
    return {
        "event": "child_import",
        "rows": job.total_rows,
        "children_created": job.created_count + job.attached_count,
        "parents_created": job.parents_created_count,
        "attached_to_existing_parent": job.attached_count,
        "linked_to_existing_child": job.linked_count,
        "enrolled_in_groups": job.enrolled_count,
        "skipped": job.skipped_count,
    }


def record_import_audit(job: ImportJob) -> None:
    AuditLog.record(
        actor=job.created_by,
        action=IMPORT_AUDIT_ACTION,
        entity=job,
        after=import_audit_summary(job),
    )


class RollbackNotAllowed(Exception):
    pass


def _ids(job: ImportJob, key: str) -> list:
    return (job.created_objects or {}).get(key) or []


def rollback_blockers(job: ImportJob) -> list[str]:
    """Откат — страховка на первый прогон, «пока никто не начал работать с
    данными» (ТЗ). Любой след работы с импортированным — причина отказа:
    откат не должен молча снести чужую работу. Пустой список — можно.

    _base_manager — чтобы видеть и мягко удалённые записи: удаление
    импортированного ребёнка вручную — тоже «работа с данными»."""
    from domains.scheduling.groups.models import GroupMembership

    if job.job_type != ImportJob.JobType.EXECUTE or job.status != ImportJob.Status.DONE:
        return ["откатить можно только завершённый импорт"]
    if job.rolled_back_at:
        return ["импорт уже откатан"]
    if not job.created_objects or not job.finished_at:
        # Импорты, выполненные до появления отката, не запоминали созданное.
        return ["для этого импорта не сохранён список созданных записей"]

    children = _ids(job, "children")
    parents = _ids(job, "parents")
    contacts = _ids(job, "child_contacts")
    memberships = _ids(job, "group_memberships")
    phones = _ids(job, "phones")
    blockers = []

    child_qs = Child._base_manager.filter(id__in=children)
    if child_qs.filter(subscriptions__isnull=False).exists():
        blockers.append("у импортированных детей уже есть абонементы")
    if child_qs.filter(lesson_consumptions__isnull=False).exists():
        blockers.append("у импортированных детей уже есть списания занятий")
    if CommunicationLog._base_manager.filter(child_id__in=children).exists():
        blockers.append("по импортированным детям уже есть записи коммуникаций")
    if (
        GroupMembership._base_manager.filter(child_id__in=children)
        .exclude(id__in=memberships)
        .exists()
    ):
        blockers.append("импортированных детей уже записывали в группы вручную")
    if (
        ChildContact._base_manager.filter(
            Q(child_id__in=children) | Q(parent_contact_id__in=parents)
        )
        .exclude(id__in=contacts)
        .exists()
    ):
        blockers.append("к импортированным детям или родителям уже привязаны другие контакты")
    if (
        ContactPhone._base_manager.filter(parent_contact_id__in=parents)
        .exclude(id__in=phones)
        .exists()
    ):
        blockers.append("импортированным родителям уже добавляли телефоны")

    touched = Q(updated_at__gt=job.finished_at) | Q(deleted_at__isnull=False)
    for model, ids in (
        (Child, children),
        (ParentContact, parents),
        (ChildContact, contacts),
        (ContactPhone, phones),
        (GroupMembership, memberships),
    ):
        if model._base_manager.filter(id__in=ids).filter(touched).exists():
            blockers.append("импортированные записи уже редактировали или удаляли")
            break
    return blockers


def rollback_import(job: ImportJob, actor) -> None:
    """Возвращает систему в состояние до импорта: всё, что создал импорт,
    мягко удаляется (ТЗ п. 3.2 — физического удаления нет), направления,
    добавленные существующим детям, снимаются. Существующие записи импорт
    не менял (привязка к существующему ребёнку — новая строка
    ChildContact, не правка старой), поэтому возвращать их не нужно."""
    from domains.scheduling.groups.models import GroupMembership

    with transaction.atomic():
        job = ImportJob.objects.select_for_update().get(pk=job.pk)
        blockers = rollback_blockers(job)
        if blockers:
            raise RollbackNotAllowed("; ".join(blockers))

        now = timezone.now()
        for model, key in (
            (GroupMembership, "group_memberships"),
            (ChildContact, "child_contacts"),
            (ContactPhone, "phones"),
            (ParentContact, "parents"),
            (Child, "children"),
        ):
            model._base_manager.filter(
                organization=job.organization, id__in=_ids(job, key), deleted_at__isnull=True
            ).update(deleted_at=now)

        by_direction: dict[str, list[str]] = {}
        for child_id, direction_id in _ids(job, "child_directions"):
            by_direction.setdefault(direction_id, []).append(child_id)
        for direction_id, child_ids in by_direction.items():
            Child.directions.through.objects.filter(
                direction_id=direction_id, child_id__in=child_ids
            ).delete()

        job.rolled_back_at = now
        job.rolled_back_by = actor
        job.save(update_fields=["rolled_back_at", "rolled_back_by"])
        AuditLog.record(
            actor=actor,
            action=IMPORT_ROLLBACK_AUDIT_ACTION,
            entity=job,
            before=import_audit_summary(job),
            after={"event": "child_import_rollback"},
        )
