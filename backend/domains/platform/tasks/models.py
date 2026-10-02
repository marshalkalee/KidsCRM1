from django.conf import settings
from django.db import models

from domains.platform.core.models import TenantModel


class Task(TenantModel):
    """Рабочая задача сотруднику.

    TRU-104 создала минимальный контракт (тип, исполнитель, срок, статус,
    заявка) для сценария «не пришёл на пробное». TRU-106 достраивает его
    до общего модуля (ТЗ п. 3.1): типы по спецификации, связь с ребёнком
    (не только с заявкой), филиал — для прав по ролям (ТЗ п. 2), источник
    — человек или автоправило, комментарий при закрытии.
    """

    class Type(models.TextChoices):
        TRIAL_NO_SHOW = "trial_no_show", "Не пришёл на пробное"
        MISSING_SUBSCRIPTION = "missing_subscription", "Нет абонемента"
        RETENTION = "retention", "Удержание клиента"
        CALL_BACK = "call_back", "Перезвонить"
        PAYMENT_REMINDER = "payment_reminder", "Напомнить об оплате"
        TRIAL_SIGNUP = "trial_signup", "Записать на пробное"
        RENEWAL_OFFER = "renewal_offer", "Предложить продление"
        OTHER = "other", "Другое"

    class Status(models.TextChoices):
        OPEN = "open", "Открыта"
        DONE = "done", "Выполнена"
        CANCELLED = "cancelled", "Отменена"

    class Source(models.TextChoices):
        MANUAL = "manual", "Вручную"
        AUTO = "auto", "Автоправило"

    type = models.CharField(max_length=32, choices=Type.choices, default=Type.OTHER)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.MANUAL)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    closing_comment = models.CharField(max_length=500, blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tasks",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_tasks",
    )
    due_at = models.DateTimeField(null=True, blank=True)
    lead = models.ForeignKey(
        "leads.Lead",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="tasks",
    )
    child = models.ForeignKey(
        "clients.Child",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="tasks",
    )
    branch = models.ForeignKey(
        "tenants.Branch",
        on_delete=models.SET_NULL,
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
            models.Index(fields=["organization", "child", "status"]),
            models.Index(fields=["organization", "branch", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "type", "source_key"],
                condition=(
                    ~models.Q(source_key="")
                    & models.Q(deleted_at__isnull=True)
                    & models.Q(status="open")
                ),
                name="unique_automatic_task_source",
            )
        ]

    def __str__(self):
        return self.title


class RuleRun(TenantModel):
    """Лог срабатывания автоправила (ТЗ п. 5.2, TRU-108) — какое правило,
    когда, сколько задач реально создало (а не просто «отработало»)."""

    rule = models.CharField(max_length=64)
    tasks_created = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["organization", "rule", "created_at"])]

    def __str__(self):
        return f"{self.rule}: {self.tasks_created}"
