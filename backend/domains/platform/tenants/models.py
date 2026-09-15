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
