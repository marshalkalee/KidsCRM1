"""
Центр уведомлений сотрудника (ТЗ п. 4.5; TRU-72).

Сами уведомления не хранятся — считаются на лету из живых данных
(sources.py): новая заявка, занятие без отметки, долг. Если хранить их
копией, копия разойдётся с экранами, а критерий приёмки — «счётчики
совпадают с содержимым экранов». Хранится только то, что видел сотрудник:
когда он в последний раз открыл уведомление этого вида.
"""

from django.conf import settings
from django.db import models

from domains.platform.core.models import UUIDPrimaryKeyModel


class NotificationSeen(UUIDPrimaryKeyModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications_seen"
    )
    kind = models.CharField(max_length=40)
    seen_at = models.DateTimeField()
    # Для видов без естественного времени события (дети без абонемента,
    # просроченные долги): «новое» — если стало больше, чем было при просмотре.
    seen_count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "kind"], name="notification_seen_unique_user_kind"
            )
        ]
