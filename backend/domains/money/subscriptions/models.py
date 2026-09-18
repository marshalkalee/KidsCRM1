from django.db import models

from domains.platform.core.models import TenantModel
from domains.platform.tenants.models import Branch, Direction

RULES_SCHEMA_VERSION = 1
# Отсутствующий ключ = правило ещё не решено с Дарьей/True Ballet — UI
# обязан допускать любое значение до ответа (Discovery, вопрос №1).
RULES_KEYS = {
    "expire_on_miss",  # bool | None — сгорает ли пропущенное занятие
    "makeup_window_days",  # int | None — срок отработки, дней
    "freezes_per_year",  # int | None — сколько заморозок разрешено в год
}


class SubscriptionType(TenantModel):
    name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=12, decimal_places=0)

    is_unlimited = models.BooleanField(default=False)
    quota_sessions = models.PositiveSmallIntegerField(null=True, blank=True)
    duration_days = models.PositiveSmallIntegerField()
    rules = models.JSONField(default=dict, blank=True)

    directions = models.ManyToManyField(Direction, related_name="subscription_types", blank=True)
    branches = models.ManyToManyField(Branch, related_name="subscription_types", blank=True)

    is_active = models.BooleanField(default=True)

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
    subscription_type = models.ForeignKey(
        SubscriptionType,
        on_delete=models.PROTECT,
        related_name="versions",
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

    class DiscountReason(models.TextChoices):
        LARGE_FAMILY = "large_family", "Многодетная семья"
        SECOND_CHILD = "second_child", "Второй ребёнок"
        PROMOTION = "promotion", "Акция"
        STAFF = "staff", "Сотрудник"
        OTHER = "other", "Другое"

    # Как у Child.ALLOWED_STATUS_TRANSITIONS (domains.people.clients) — единый
    # источник правды. EXPIRED/EXHAUSTED терминальны: продление — новая покупка.
    ALLOWED_STATUS_TRANSITIONS = {
        Status.ACTIVE: {Status.FROZEN, Status.EXPIRED, Status.EXHAUSTED},
        Status.FROZEN: {Status.ACTIVE, Status.EXPIRED},
        Status.EXPIRED: set(),
        Status.EXHAUSTED: set(),
    }

    child = models.ForeignKey(
        "clients.Child", on_delete=models.PROTECT, related_name="subscriptions"
    )
    subscription_type_version = models.ForeignKey(
        SubscriptionTypeVersion,
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    direction = models.ForeignKey(
        "tenants.Direction", on_delete=models.PROTECT, related_name="subscriptions"
    )

    starts_on = models.DateField()
    ends_on = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)

    # Кэш, не источник правды (ТЗ п. 3.2) — источник: SubscriptionLedgerEntry.
    sessions_remaining_cache = models.SmallIntegerField(null=True, blank=True)

    list_price = models.DecimalField(max_digits=12, decimal_places=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    discount_reason = models.CharField(max_length=20, choices=DiscountReason.choices, blank=True)
    discount_comment = models.CharField(max_length=255, blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=0)  # = list_price - discount_amount

    class Meta:
        ordering = ["-starts_on"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(discount_amount=0) | ~models.Q(discount_reason=""),
                name="subscription_discount_requires_reason",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.child} — {self.subscription_type_version.name} ({self.get_status_display()})"

    def can_transition_to(self, new_status: str) -> bool:
        return new_status in self.ALLOWED_STATUS_TRANSITIONS.get(self.status, set())


class SubscriptionLedgerEntry(TenantModel):
    class Kind(models.TextChoices):
        INITIAL_GRANT = "initial_grant", "Начисление при продаже"
        CONSUMPTION = "consumption", "Списание за посещение"
        MANUAL_ADJUSTMENT = "manual_adjustment", "Ручная корректировка"
        EXTENSION = "extension", "Продление"

    subscription = models.ForeignKey(
        Subscription, on_delete=models.CASCADE, related_name="ledger_entries"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    delta = models.SmallIntegerField()
    comment = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.subscription} {self.delta:+d} ({self.get_kind_display()})"


class SubscriptionFreeze(TenantModel):
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="freezes")
    starts_on = models.DateField()
    ends_on = models.DateField(null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-starts_on"]


class LessonConsumption(TenantModel):
    """Идемпотентность consume()/revert() (TRU-8, контракт №1). lesson_id —
    обычный UUID, не FK: Lesson ещё не существует (TRU-50 не сделан), сервис
    подписок не должен зависеть от домена расписания."""

    child = models.ForeignKey(
        "clients.Child", on_delete=models.PROTECT, related_name="lesson_consumptions"
    )
    lesson_id = models.UUIDField()
    subscription = models.ForeignKey(
        Subscription, on_delete=models.PROTECT, related_name="lesson_consumptions"
    )
    ledger_entry = models.ForeignKey(
        SubscriptionLedgerEntry, on_delete=models.PROTECT, related_name="+"
    )
    reverted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["child", "lesson_id"],
                condition=models.Q(reverted_at__isnull=True),
                name="unique_active_consumption_per_child_lesson",
            ),
        ]


class BalanceDiscrepancy(TenantModel):
    """Найдено фоновой сверкой (ТЗ п. 3.2, 11.3). Кэш чинится сразу же при
    обнаружении — запись остаётся как история для отчёта: если расхождения
    появляются регулярно, это баг, а не разовая гонка."""

    subscription = models.ForeignKey(
        Subscription, on_delete=models.CASCADE, related_name="discrepancies"
    )
    cached_value = models.SmallIntegerField(null=True)
    recomputed_value = models.SmallIntegerField(null=True)
    found_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-found_at"]

    def __str__(self) -> str:
        return (
            f"{self.subscription}: {self.cached_value} -> {self.recomputed_value} "
            f"({self.found_at:%d.%m.%Y})"
        )