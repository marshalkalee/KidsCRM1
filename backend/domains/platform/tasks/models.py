from django.conf import settings
from django.db import models

from domains.platform.core.models import TenantModel


class Task(TenantModel):
    """Рабочая задача сотруднику.

    TRU-104 использует минимальный общий контракт будущего модуля задач:
    тип, исполнитель, срок, статус и ссылка на заявку. ``source_key``
    делает автоматические задачи идемпотентными — повторное сохранение той
    же отметки посещения не создаёт второй звонок.
    """

    class Type(models.TextChoices):
        TRIAL_NO_SHOW = "trial_no_show", "Не пришёл на пробное"
        MISSING_SUBSCRIPTION = "missing_subscription", "Нет абонемента"
        RETENTION = "retention", "Удержание клиента"
        OTHER = "other", "Другое"

    class Status(models.TextChoices):
        OPEN = "open", "Открыта"
        DONE = "done", "Выполнена"
        CANCELLED = "cancelled", "Отменена"

    type = models.CharField(max_length=32, choices=Type.choices, default=Type.OTHER)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tasks",
    )
    due_at = models.DateTimeField(null=True, blank=True)
    lead = models.ForeignKey(
        "leads.Lead",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="tasks",
    )
    source_key = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["status", "due_at", "-created_at"]
        indexes = [
            models.Index(fields=["organization", "assigned_to", "status", "due_at"]),
            models.Index(fields=["organization", "lead", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "type", "source_key"],
                condition=~models.Q(source_key="") & models.Q(deleted_at__isnull=True),
                name="unique_automatic_task_source",
            )
        ]

    def __str__(self):
        return self.title
