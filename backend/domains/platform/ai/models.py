"""
Сохранённые чаты с ИИ (ai/chat.py): переписка переживает закрытие
вкладки и вход с другого устройства. Чат видит только его автор — это
его вопросы о центре, не общая лента.
"""

from django.conf import settings
from django.db import models

from domains.platform.core.models import TenantModel


class AIConversation(TenantModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_conversations"
    )
    # Первый вопрос, обрезанный, — так чат узнают в истории.
    title = models.CharField(max_length=120)
    # Метки имён этого чата ({"[N1]": "Бекова Алия"}, ai/pseudonyms.py):
    # модель видит метки, имена — только здесь, у нас. Хранятся с чатом,
    # чтобы метка человека не менялась от вопроса к вопросу.
    pseudonyms = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["user", "-updated_at"])]

    def __str__(self) -> str:
        return self.title


class AIMessage(models.Model):
    class Role(models.TextChoices):
        USER = "user", "Вопрос"
        ASSISTANT = "assistant", "Ответ"

    conversation = models.ForeignKey(
        AIConversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField()
    # Что ИИ посмотрел для ответа: «задолженности», «расписание».
    sources = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self) -> str:
        return f"{self.get_role_display()}: {self.content[:40]}"


class AIGeneration(TenantModel):
    """Один фоновый запуск версионированного промпта (TRU-159)."""

    class Status(models.TextChoices):
        QUEUED = "queued", "В очереди"
        RUNNING = "running", "Выполняется"
        SUCCEEDED = "succeeded", "Готово"
        PROVIDER_UNAVAILABLE = "provider_unavailable", "Провайдер недоступен"
        SCHEMA_ERROR = "schema_error", "Ответ не прошёл проверку"
        LIMIT_EXHAUSTED = "limit_exhausted", "Лимит исчерпан"
        NO_KEY = "no_key", "ИИ не настроен"
        INPUT_TOO_LARGE = "input_too_large", "Слишком большой запрос"

    function = models.CharField(max_length=64)
    prompt_version = models.CharField(max_length=32)
    provider = models.CharField(max_length=20, blank=True)
    model = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.QUEUED)
    attempts = models.PositiveSmallIntegerField(default=0)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    request_chars = models.PositiveIntegerField(default=0)
    result = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_detail = models.CharField(max_length=500, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "function", "-created_at"]),
            models.Index(fields=["organization", "status", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.function}@{self.prompt_version}: {self.status}"


class AIRecommendationState(TenantModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Активна"
        DISMISSED = "dismissed", "Отклонена"

    function = models.CharField(max_length=64)
    candidate_key = models.CharField(max_length=64)
    fingerprint = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    times_shown = models.PositiveSmallIntegerField(default=0)
    payload = models.JSONField(default=dict, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "function", "fingerprint"],
                name="unique_ai_recommendation_fingerprint",
            )
        ]
        indexes = [models.Index(fields=["organization", "function", "status"])]
class AIUsage(TenantModel):
    """Одно обращение к модели (TRU-160, ADR-0009 раздел 5): на этих строках
    стоят счётчик месяца, лимит центра и сводка платформы. Пишется сразу
    после ответа провайдера — что бы ни случилось дальше, токены учтены."""

    feature = models.CharField(max_length=64)
    model = models.CharField(max_length=100)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    # Стоимость по таблице AI_PRICES_USD на момент вызова — цены меняются,
    # прошлые месяцы пересчитывать не нужно.
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    generation = models.ForeignKey(
        AIGeneration, null=True, blank=True, on_delete=models.SET_NULL, related_name="usage"
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["organization", "created_at"])]

    def __str__(self) -> str:
        return f"{self.feature} {self.model}: {self.input_tokens}/{self.output_tokens}"


class AIDigest(TenantModel):
    """Еженедельный дайджест владельцу (TRU-163): что сделать на этой неделе.

    Собирается фоновой задачей из блоков — шаблонов слоя генераций
    (digest.BLOCKS). content — готовая для экрана структура: главное с
    цифрами, блоки целиком, что изменилось с прошлого. Прошлые не
    удаляются: по архиву видно, что советовали и сработало ли."""

    class Status(models.TextChoices):
        QUEUED = "queued", "В очереди"
        RUNNING = "running", "Собирается"
        READY = "ready", "Готов"
        INSUFFICIENT_DATA = "insufficient_data", "Данных пока мало"
        LIMIT_EXHAUSTED = "limit_exhausted", "Лимит исчерпан"
        FAILED = "failed", "Не собрался"

    class Trigger(models.TextChoices):
        SCHEDULE = "schedule", "По расписанию"
        MANUAL = "manual", "Кнопка «Обновить»"

    # Понедельник недели по времени центра: к какой неделе относится.
    week_start = models.DateField()
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.QUEUED)
    trigger = models.CharField(max_length=16, choices=Trigger.choices)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    content = models.JSONField(default=dict, blank=True)
    error_detail = models.CharField(max_length=500, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["organization", "status", "-created_at"])]

    def __str__(self) -> str:
        return f"Дайджест {self.week_start}: {self.status}"
