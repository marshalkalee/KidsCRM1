"""
Ребёнок — центральная сущность системы (ТЗ п. 3.1): на неё ссылаются
посещения, абонементы, оплаты и заявки. Направления (Direction) уже
существуют (домен platform.tenants) — связь заведена здесь. Группы делает
Дарья отдельным тикетом; связь с группами появится с её стороны, когда
модель Group будет существовать — заводить её здесь заранее не на чём.

ИИН ребёнка не хранится и не появится как поле — принцип минимизации
данных (ТЗ п. 10.3): система не нуждается в нём для своей работы.
"""

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models, transaction
from django.utils import timezone

from domains.platform.core.models import TenantModel
from domains.platform.core.phone import normalize_phone_number


class Child(TenantModel):
    class Gender(models.TextChoices):
        MALE = "male", "Мужской"
        FEMALE = "female", "Женский"

    class Status(models.TextChoices):
        ACTIVE = "active", "Активен"
        PAUSED = "paused", "Приостановлен"
        LEFT = "left", "Ушёл"

    # Единый источник правды для допустимых переходов статуса — используется
    # и сериализатором API, и тестами, чтобы не разойтись в двух местах.
    # LEFT -> ACTIVE разрешён (семья может вернуться); PAUSED -> LEFT тоже
    # (пауза может закончиться уходом), а LEFT -> PAUSED не имеет смысла —
    # сначала возврат в ACTIVE, потом обычная пауза при необходимости.
    ALLOWED_STATUS_TRANSITIONS = {
        Status.ACTIVE: {Status.PAUSED, Status.LEFT},
        Status.PAUSED: {Status.ACTIVE, Status.LEFT},
        Status.LEFT: {Status.ACTIVE},
    }

    full_name = models.CharField(max_length=255)
    birth_date = models.DateField()
    gender = models.CharField(max_length=10, choices=Gender.choices)
    directions = models.ManyToManyField("tenants.Direction", related_name="children", blank=True)
    medical_notes = models.TextField(blank=True)
    # URL, а не ImageField: загрузка/хранение файлов — отдельная инфраструктура
    # (Pillow, MEDIA_ROOT, storage backend), которую этот тикет не заводит;
    # поле опционально по ТЗ, URL этому не противоречит.
    photo_url = models.URLField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    # Обязательность при статусе LEFT проверяется на уровне API (сериализатор),
    # не здесь — иначе поле было бы обязательным для всех статусов сразу.
    leave_reason = models.TextField(blank=True)
    consent_given = models.BooleanField(default=False)

    class Meta:
        ordering = ["full_name"]
        # Частичные индексы (condition=deleted_at IS NULL) — под тем же
        # фильтром, что уже всегда накладывает SoftDeleteQuerySet.alive(),
        # поэтому индекс реально покрывает то, что запросы фактически
        # исполняют, а не полную таблицу с историческими (удалёнными)
        # строками (ТЗ п. 10.2 — список на 5000 детей, сортировки/фильтры).
        indexes = [
            models.Index(
                fields=["organization", "full_name"],
                name="child_org_full_name_idx",
                condition=models.Q(deleted_at__isnull=True),
            ),
            models.Index(
                fields=["organization", "birth_date"],
                name="child_org_birth_date_idx",
                condition=models.Q(deleted_at__isnull=True),
            ),
            models.Index(
                fields=["organization", "status"],
                name="child_org_status_idx",
                condition=models.Q(deleted_at__isnull=True),
            ),
            # GIN + gin_trgm_ops (pg_trgm, включено в 0001_baseline) — под
            # частичное совпадение без учёта регистра (ТЗ п. 4.1, 10.2:
            # быстрый поиск, 3 символа среди 5000 детей ≤1с). Обычный
            # B-tree выше не ускоряет ILIKE '%...%' — только точное
            # совпадение/сортировку по началу строки.
            GinIndex(
                fields=["full_name"],
                name="child_full_name_trgm_idx",
                opclasses=["gin_trgm_ops"],
            ),
        ]

    def __str__(self) -> str:
        return self.full_name

    @property
    def age(self) -> int:
        """Возраст на сегодня — не хранится, чтобы не протухать на следующий
        день рождения. Корректен и в день рождения: (месяц, день) сравниваются
        как пара, а не по отдельности."""
        today = timezone.now().date()
        years = today.year - self.birth_date.year
        if (today.month, today.day) < (self.birth_date.month, self.birth_date.day):
            years -= 1
        return years


class ParentContact(TenantModel):
    """
    Родитель или контактное лицо ребёнка (ТЗ п. 1.2.1, п. 3.1: Parent /
    ContactPerson — одна и та же форма контакта в этом тикете; связь с
    Child и тип отношения — родитель/бабушка/может забирать и т.п. —
    отдельная задача, здесь её нет).

    Телефоны — не одно поле, а связанная модель ContactPhone: у родителя
    обычно несколько (рабочий/личный), и администратор звонит по любому
    (ТЗ п. 4.1).
    """

    full_name = models.CharField(max_length=255)
    # Может отличаться от любого из phones — отдельное поле, не тип в
    # ContactPhone (ТЗ явно разделяет их как разные пункты).
    whatsapp = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)

    class Meta:
        ordering = ["full_name"]
        # GIN + gin_trgm_ops — быстрый поиск по родителю (ТЗ п. 4.1,
        # единый поиск по имени ребёнка/родителя/телефону).
        indexes = [
            GinIndex(
                fields=["full_name"],
                name="pc_full_name_trgm_idx",
                opclasses=["gin_trgm_ops"],
            ),
            GinIndex(
                fields=["whatsapp"],
                name="pc_whatsapp_trgm_idx",
                opclasses=["gin_trgm_ops"],
            ),
        ]

    def __str__(self) -> str:
        return self.full_name

    def save(self, *args, **kwargs):
        if self.whatsapp:
            self.whatsapp = normalize_phone_number(self.whatsapp)
        super().save(*args, **kwargs)


class ContactPhone(TenantModel):
    class PhoneType(models.TextChoices):
        MOBILE = "mobile", "Мобильный"
        WORK = "work", "Рабочий"
        HOME = "home", "Домашний"

    parent_contact = models.ForeignKey(
        ParentContact, on_delete=models.CASCADE, related_name="phones"
    )
    number = models.CharField(max_length=20)
    phone_type = models.CharField(
        max_length=10, choices=PhoneType.choices, default=PhoneType.MOBILE
    )

    class Meta:
        ordering = ["parent_contact_id", "phone_type"]
        indexes = [
            # GIN + gin_trgm_ops — поиск по телефону (частичный: последние
            # 4 цифры и т.п., ТЗ п. 4.1 критерий приёмки).
            GinIndex(
                fields=["number"],
                name="cp_number_trgm_idx",
                opclasses=["gin_trgm_ops"],
            ),
        ]

    def __str__(self) -> str:
        return self.number

    def save(self, *args, **kwargs):
        # organization выводится из parent_contact, а не принимается
        # отдельно — та же логика, что у Room (выводится из branch), чтобы
        # for_tenant() не требовал JOIN (ADR-001).
        self.organization_id = self.parent_contact.organization_id
        self.number = normalize_phone_number(self.number)
        super().save(*args, **kwargs)


class ChildContact(TenantModel):
    """
    Связь ребёнок <-> родитель/контактное лицо — многие-ко-многим со своими
    атрибутами (ТЗ п. 1.2.1, п. 3.1), не FK на Child: у ребёнка может быть
    несколько контактов (мама, папа, бабушка), у контакта — несколько детей.

    Правило про плательщика (согласовано с Bekzat — от него зависит расчёт
    задолженности): у ребёнка не может быть больше ОДНОГО активного
    плательщика одновременно. save() сам снимает флаг с предыдущего —
    отдельного действия "назначить" не нужно, назначение — это просто
    is_payer=True на нужной связи. UniqueConstraint ниже — тот же инвариант
    на уровне БД (страховка от bulk_update/сырых запросов мимо save()).

    Отвязка (detach) — мягкое удаление этой строки, не Child и не
    ParentContact: будущие оплаты у Bekzat'а должны ссылаться на
    ParentContact напрямую, а не на эту связь, — тогда отвязка контакта не
    роняет историю платежей.
    """

    class Role(models.TextChoices):
        MOTHER = "mother", "Мама"
        FATHER = "father", "Папа"
        GUARDIAN = "guardian", "Опекун"
        GRANDMOTHER = "grandmother", "Бабушка"
        OTHER = "other", "Другое"

    child = models.ForeignKey(Child, on_delete=models.CASCADE, related_name="contacts")
    parent_contact = models.ForeignKey(
        ParentContact, on_delete=models.CASCADE, related_name="child_links"
    )
    role = models.CharField(max_length=20, choices=Role.choices)
    is_payer = models.BooleanField(default=False)
    is_primary_contact = models.BooleanField(default=False)

    class Meta:
        ordering = ["child_id", "-is_primary_contact", "role"]
        constraints = [
            models.UniqueConstraint(
                fields=["child", "parent_contact"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_active_child_parent_contact",
            ),
            models.UniqueConstraint(
                fields=["child"],
                condition=models.Q(is_payer=True, deleted_at__isnull=True),
                name="unique_active_payer_per_child",
            ),
            models.UniqueConstraint(
                fields=["child"],
                condition=models.Q(is_primary_contact=True, deleted_at__isnull=True),
                name="unique_active_primary_contact_per_child",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.parent_contact_id} -> {self.child_id} ({self.role})"

    def save(self, *args, **kwargs):
        self.organization_id = self.child.organization_id
        with transaction.atomic():
            if self.is_payer:
                type(self).objects.filter(child=self.child, is_payer=True).exclude(
                    pk=self.pk
                ).update(is_payer=False)
            if self.is_primary_contact:
                type(self).objects.filter(child=self.child, is_primary_contact=True).exclude(
                    pk=self.pk
                ).update(is_primary_contact=False)
            super().save(*args, **kwargs)


class CommunicationLog(TenantModel):
    """
    История контактов с родителем — вкладка «Коммуникации» карточки
    ребёнка (ТЗ п. 3.1, п. 4.1). На старте (M1) записи заводятся вручную:
    администратор фиксирует звонок/WhatsApp/комментарий после факта, поэтому
    полей здесь минимум — быстрый ввод важнее полноты (см. web_views.py:
    критерий приёмки "за пару кликов, иначе вкладка останется пустой").

    parent_contact — опционален: не всегда звонок был конкретному контакту
    (иногда это просто внутренняя заметка о ребёнке), но когда известен,
    даёт "историю по родителю", а не только по ребёнку.

    Append-only: записи не редактируются и не удаляются (это лог, а не
    черновик) — отдельного UI для этого нет и не планируется здесь.
    """

    class Channel(models.TextChoices):
        CALL = "call", "Звонок"
        WHATSAPP = "whatsapp", "WhatsApp"
        COMMENT = "comment", "Комментарий"

    child = models.ForeignKey(Child, on_delete=models.CASCADE, related_name="communication_logs")
    parent_contact = models.ForeignKey(
        ParentContact,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="communication_logs",
    )
    # default — иначе Django добавляет в выбор канала пустой "---------"
    # вариант (для required-поля без default), и он же на быстрой форме
    # оказывался выбран по умолчанию: невозможно "добавить запись", ничего
    # не выбрав, что путает интерфейс.
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.CALL)
    note = models.TextField()
    # PROTECT — лог не должен потерять автора молча (нужен для аудита);
    # пользователи и так мягко удаляются (User.delete()), так что PROTECT
    # здесь не мешает обычному увольнению сотрудника.
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="communication_logs"
    )

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        self.organization_id = self.child.organization_id
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.get_channel_display()} — {self.child_id} ({self.created_at:%Y-%m-%d})"


class ImportColumnMapping(TenantModel):
    """Сохранённый маппинг колонок файла → поля системы (ТЗ п. 4.1) —
    повторный импорт файла с тем же составом колонок не требует
    настраивать заново. Ключ — точный набор заголовков (headers_key), не
    имя файла: два разных файла с одинаковыми колонками должны получить
    один и тот же сохранённый маппинг."""

    # "|".join(file_headers) — для быстрого поиска/уникальности; JSONField
    # саму по себе так индексировать/сравнивать неудобно.
    headers_key = models.CharField(max_length=1000)
    file_headers = models.JSONField()
    mapping = models.JSONField()  # {"child_name": "ФИО ребёнка", ...}
    csv_delimiter = models.CharField(max_length=4, blank=True)
    csv_encoding = models.CharField(max_length=32, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "headers_key"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_active_mapping_per_headers",
            ),
        ]

    def __str__(self) -> str:
        return f"Маппинг {self.organization_id} ({len(self.file_headers)} колонок)"


class ImportJob(TenantModel):
    """Импорт файла — фоновая задача (ТЗ п. 10.1), не HTTP-запрос: на
    файле в тысячи строк дедуп (ChildService.find_duplicates на каждую
    новую семью) и создание записей не укладываются в бюджет одного
    запроса. rows_payload — уже распознанные и провалидированные строки
    (ImportRow.to_dict()) на момент постановки в очередь; сам дедуп
    (resolve_rows) и создание (execute_import) выполняет tasks.py.

    Два вида задачи (job_type) — сухой прогон (ТЗ п. 4.1, тикет
    «валидация, сухой прогон и отчёт об ошибках») и настоящее выполнение.
    Общая модель, а не две разные: оба вида парсят один и тот же
    rows_payload и проходят один и тот же resolve_rows — расхождение
    логики дедупа между "проверить" и "сделать" было бы худшим исходом,
    чем небольшое дублирование пары полей результата."""

    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает"
        RUNNING = "running", "Выполняется"
        DONE = "done", "Готово"
        FAILED = "failed", "Ошибка"

    class JobType(models.TextChoices):
        DRY_RUN = "dry_run", "Сухой прогон"
        EXECUTE = "execute", "Импорт"

    job_type = models.CharField(max_length=10, choices=JobType.choices, default=JobType.EXECUTE)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    total_rows = models.PositiveIntegerField(default=0)
    rows_payload = models.JSONField()

    # JobType.EXECUTE.
    created_count = models.PositiveIntegerField(default=0)
    attached_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    failed_rows = models.JSONField(default=list, blank=True)  # [[row_number, error], ...]
    unhandled_balances = models.JSONField(default=list, blank=True)

    # JobType.DRY_RUN — см. import_service.build_dry_run_report.
    ready_count = models.PositiveIntegerField(default=0)
    warning_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    report_rows = models.JSONField(default=list, blank=True)
    # Импорт, уже запущенный из этого сухого прогона — один сухой прогон
    # даёт максимум один импорт (повторное нажатие / двойной клик не
    # создаёт вторую задачу, см. import_views.child_import_execute).
    executed_job = models.OneToOneField(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_dry_run",
    )

    error_message = models.TextField(blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_job_type_display()} {self.id} ({self.get_status_display()})"
