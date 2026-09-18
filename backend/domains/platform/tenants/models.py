from django.core.validators import RegexValidator
from django.db import models

from domains.platform.core.models import SoftDeleteManager, TenantModel, TimestampedSoftDeleteModel


class Organization(TimestampedSoftDeleteModel):
    """
    Корень модели данных — тенант (ТЗ п. 1.2.3, п. 3.1; см. согласованную
    схему backend/docs/db-schema-v1 на ветке feature/db-schema-v1).

    `timezone` и `settings` — из формулировки этой задачи, в db-schema-v1
    их пока нет явно; если схема не должна их содержать — снять здесь,
    но без них Organization не может задать часовой пояс по умолчанию
    (ТЗ п. 3.2: Asia/Almaty по умолчанию для расчёта расписания).
    """

    class SubscriptionStatus(models.TextChoices):
        TRIAL = "trial", "Триал"
        ACTIVE = "active", "Активна"
        SUSPENDED = "suspended", "Приостановлена"

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=100, unique=True)
    plan = models.CharField(max_length=50, blank=True)
    subscription_status = models.CharField(
        max_length=20,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.TRIAL,
    )
    is_active = models.BooleanField(default=True)
    timezone = models.CharField(max_length=64, default="Asia/Almaty")
    settings = models.JSONField(default=dict, blank=True)

    objects = SoftDeleteManager()

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Branch(TenantModel):
    name = models.CharField(max_length=255)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    working_hours = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.organization_id})"


class Room(TenantModel):
    """Зал внутри филиала — нужен для детекта конфликтов расписания (ТЗ п. 4.2)."""

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="rooms")
    name = models.CharField(max_length=100)
    capacity = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["branch_id", "name"]

    def save(self, *args, **kwargs):
        # organization всегда выводится из branch, а не принимается отдельно
        # — иначе клиент мог бы указать несогласованную пару branch/organization.
        self.organization_id = self.branch.organization_id
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} @ {self.branch_id}"


class Direction(TenantModel):
    """
    Направление (балет, гимнастика, английский) — справочник, на который
    ссылаются группы (домен Дарьи), типы абонементов (домен Bekzat'а),
    заявки и аналитика (ТЗ п. 3.1). Принадлежит организации целиком, а не
    филиалу — сеть с одним "балетом" на всю сеть не должна заводить его
    в каждом филиале заново, только отметить, где он доступен (см.
    `branches` — M2M, не ForeignKey).
    """

    HEX_COLOR_VALIDATOR = RegexValidator(r"^#[0-9A-Fa-f]{6}$", "Цвет — HEX-код вида #7C6FF7.")

    name = models.CharField(max_length=255)
    # Дефолт — акцентный цвет из дизайн-системы (tokens.css), чтобы новое
    # направление не заводилось без цвета "просто чёрным" в календаре.
    color = models.CharField(max_length=7, default="#7C6FF7", validators=[HEX_COLOR_VALIDATOR])
    age_min = models.PositiveSmallIntegerField(null=True, blank=True)
    age_max = models.PositiveSmallIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    branches = models.ManyToManyField(Branch, related_name="directions", blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
