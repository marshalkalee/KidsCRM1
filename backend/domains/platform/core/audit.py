import functools

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from domains.platform.core.models import UUIDPrimaryKeyModel


class AuditLog(UUIDPrimaryKeyModel):
    class Action(models.TextChoices):
        CREATE = "create", "Создание"
        UPDATE = "update", "Изменение"
        DELETE = "delete", "Удаление"
        FREEZE = "freeze", "Заморозка"
        UNFREEZE = "unfreeze", "Разморозка"
        EXTEND = "extend", "Продление"
        ADJUST = "adjust", "Корректировка"
        GRANT = "grant", "Выдача прав"
        REVOKE = "revoke", "Отзыв прав"
        CANCEL = "cancel", "Отмена"
        RESCHEDULE = "reschedule", "Перенос"

    organization = models.ForeignKey(
        "tenants.Organization",
        on_delete=models.PROTECT,
        related_name="audit_logs",
    )
    actor = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=50, choices=Action.choices)

    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.UUIDField()
    entity = GenericForeignKey("content_type", "object_id")

    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["content_type", "object_id"]),
        ]

    def delete(self, *args, **kwargs):
        raise PermissionError("Записи аудита нельзя удалять.")

    def save(self, *args, **kwargs):
        if self.pk and AuditLog.objects.filter(pk=self.pk).exists():
            raise PermissionError("Записи аудита нельзя редактировать.")
        super().save(*args, **kwargs)

    @classmethod
    def record(cls, actor, action, entity, before=None, after=None):
        content_type = ContentType.objects.get_for_model(entity)
        cls.objects.create(
            organization=actor.organization if actor else entity.organization,
            actor=actor,
            action=action,
            content_type=content_type,
            object_id=entity.pk,
            before=before,
            after=after,
        )

    def __str__(self):
        return f"{self.actor} — {self.action} — {self.created_at}"


def audit_action(action):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(view, serializer, *args, **kwargs):
            instance = getattr(serializer, "instance", None)
            before = dict(serializer.data) if instance else None
            result = func(view, serializer, *args, **kwargs)
            after = dict(serializer.data)
            AuditLog.record(
                actor=view.request.user,
                action=action,
                entity=serializer.instance,
                before=before,
                after=after,
            )
            return result

        return wrapper

    return decorator
