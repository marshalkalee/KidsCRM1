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
