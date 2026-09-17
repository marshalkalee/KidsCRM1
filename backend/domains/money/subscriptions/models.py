from django.db import models  # noqa: F401
"""
Тип абонемента — справочник организации (ТЗ п. 3.1, TRU-57).

Правила (сгорание пропусков, заморозки, отработки) — JSON-блок `rules` со
`schema_version`, не фиксированные булевы поля: реальные правила True
Ballet не выяснены (Discovery, открытый вопрос №1, ТЗ п. 13.1), жёсткая
схема колонок потребовала бы миграции на первый нестандартный случай.

Subscription (TRU-58) обязан ссылаться на SubscriptionTypeVersion, а не
на "живой" SubscriptionType — иначе правка типа задним числом изменит
поведение уже проданных абонементов (критерий приёмки TRU-57).
"""

from domains.platform.core.models import TenantModel
from domains.platform.tenants.models import Branch, Direction

RULES_SCHEMA_VERSION = 1
# Отсутствующий ключ = правило ещё не решено с Дарьей/True Ballet — UI
# обязан допускать любое значение до ответа (Discovery, вопрос №1).
RULES_KEYS = {
    "expire_on_miss",      # bool | None — сгорает ли пропущенное занятие
    "makeup_window_days",  # int | None — срок отработки, дней
    "freezes_per_year",    # int | None — сколько заморозок разрешено в год
}


class SubscriptionType(TenantModel):
    name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=12, decimal_places=0)  # тенге, ТЗ п. 3.2 — не float

    is_unlimited = models.BooleanField(default=False)
    quota_sessions = models.PositiveSmallIntegerField(null=True, blank=True)
    duration_days = models.PositiveSmallIntegerField()
    rules = models.JSONField(default=dict, blank=True)

    directions = models.ManyToManyField(Direction, related_name="subscription_types", blank=True)
    branches = models.ManyToManyField(Branch, related_name="subscription_types", blank=True)

    is_active = models.BooleanField(default=True)  # архивация — не soft delete (deleted_at)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(is_unlimited=True, quota_sessions__isnull=True)
                    | models.Q(is_unlimited=False, quota_sessions__isnull=False)
                ),
                name="subscriptiontype_unlimited_xor_quota",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class SubscriptionTypeVersion(TenantModel):
    """Неизменяемый снимок — создаётся только через subscription_types.update_rules(),
    никогда не редактируется после создания."""

    subscription_type = models.ForeignKey(
        SubscriptionType, on_delete=models.PROTECT, related_name="versions",
    )
    schema_version = models.PositiveSmallIntegerField(default=RULES_SCHEMA_VERSION)

    name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=12, decimal_places=0)
    is_unlimited = models.BooleanField()
    quota_sessions = models.PositiveSmallIntegerField(null=True, blank=True)
    duration_days = models.PositiveSmallIntegerField()
    rules = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        get_latest_by = "created_at"

    def __str__(self) -> str:
        return f"{self.name} v{self.schema_version} ({self.created_at:%d.%m.%Y})"