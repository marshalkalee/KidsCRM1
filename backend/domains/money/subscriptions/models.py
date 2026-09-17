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


class Subscription(TenantModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Активен"
        EXPIRED = "expired", "Истёк"
        FROZEN = "frozen", "Заморожен"
        EXHAUSTED = "exhausted", "Исчерпан"

    # Как у Child.ALLOWED_STATUS_TRANSITIONS (domains.people.clients) — единый
    # источник правды. EXPIRED/EXHAUSTED терминальны: продление — новая покупка.
    ALLOWED_STATUS_TRANSITIONS = {
        Status.ACTIVE: {Status.FROZEN, Status.EXPIRED, Status.EXHAUSTED},
        Status.FROZEN: {Status.ACTIVE, Status.EXPIRED},
        Status.EXPIRED: set(),
        Status.EXHAUSTED: set(),
    }

    child = models.ForeignKey("clients.Child", on_delete=models.PROTECT, related_name="subscriptions")
    subscription_type_version = models.ForeignKey(
        SubscriptionTypeVersion, on_delete=models.PROTECT, related_name="subscriptions",
    )
    direction = models.ForeignKey("tenants.Direction", on_delete=models.PROTECT, related_name="subscriptions")

    starts_on = models.DateField()
    ends_on = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)

    # Кэш, не источник правды (ТЗ п. 3.2) — источник: SubscriptionLedgerEntry.
    sessions_remaining_cache = models.SmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-starts_on"]

    def __str__(self) -> str:
        return f"{self.child} — {self.subscription_type_version.name} ({self.get_status_display()})"

    def can_transition_to(self, new_status: str) -> bool:
        return new_status in self.ALLOWED_STATUS_TRANSITIONS.get(self.status, set())


class SubscriptionLedgerEntry(TenantModel):
    """Журнал — единственный источник правды для остатка (ТЗ п. 3.2).
    CONSUMPTION-записи появятся вместе с Attendance (её ещё нет ни у кого)."""

    class Kind(models.TextChoices):
        INITIAL_GRANT = "initial_grant", "Начисление при продаже"
        CONSUMPTION = "consumption", "Списание за посещение"
        MANUAL_ADJUSTMENT = "manual_adjustment", "Ручная корректировка"
        EXTENSION = "extension", "Продление"

    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="ledger_entries")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    delta = models.SmallIntegerField()
    comment = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.subscription} {self.delta:+d} ({self.get_kind_display()})"


class SubscriptionFreeze(TenantModel):
    """История заморозок (ТЗ п. 3.1). Применение заморозки (сдвиг ends_on,
    лимит из rules.freezes_per_year) — отдельная задача поверх этой записи."""

    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="freezes")
    starts_on = models.DateField()
    ends_on = models.DateField(null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-starts_on"]