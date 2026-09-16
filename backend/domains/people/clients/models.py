"""
Ребёнок — центральная сущность системы (ТЗ п. 3.1): на неё ссылаются
посещения, абонементы, оплаты и заявки. Направления (Direction) уже
существуют (домен platform.tenants) — связь заведена здесь. Группы делает
Дарья отдельным тикетом; связь с группами появится с её стороны, когда
модель Group будет существовать — заводить её здесь заранее не на чём.

ИИН ребёнка не хранится и не появится как поле — принцип минимизации
данных (ТЗ п. 10.3): система не нуждается в нём для своей работы.
"""

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
