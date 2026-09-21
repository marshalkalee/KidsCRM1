from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from domains.platform.core.models import TenantModel, TimestampedSoftDeleteModel

ALLOWED_STATUS_TRANSITIONS = {
    "scheduled": {"completed", "cancelled", "rescheduled"},
    "completed": set(),
    "cancelled": set(),
    "rescheduled": set(),
}


class Lesson(TenantModel, TimestampedSoftDeleteModel):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", _("Запланировано")
        COMPLETED = "completed", _("Проведено")
        CANCELLED = "cancelled", _("Отменено")
        RESCHEDULED = "rescheduled", _("Перенесено")

    group = models.ForeignKey(
        "groups.Group",
        on_delete=models.PROTECT,
        related_name="lessons",
        verbose_name=_("Группа"),
        null=True,
        blank=True,
        help_text=_("Null для индивидуального занятия"),
    )
    schedule_slot = models.ForeignKey(
        "schedule_templates.ScheduleTemplateSlot",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lessons",
        verbose_name=_("Слот шаблона"),
    )
    room = models.ForeignKey(
        "tenants.Room",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lessons",
        verbose_name=_("Зал"),
    )
    teacher = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="taught_lessons",
        verbose_name=_("Преподаватель"),
        limit_choices_to={"role": "teacher"},
    )

    starts_at = models.DateTimeField(_("Начало (UTC)"))
    ends_at = models.DateTimeField(_("Конец (UTC)"))

    status = models.CharField(
        _("Статус"),
        max_length=16,
        choices=Status.choices,
        default=Status.SCHEDULED,
    )

    # Связь при переносе — в обе стороны
    rescheduled_from = models.OneToOneField(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rescheduled_to",
        verbose_name=_("Перенесено из"),
        help_text=_("Исходное занятие при переносе"),
    )

    is_modified = models.BooleanField(
        _("Изменено вручную"),
        default=False,
        help_text=_(
            "True — администратор вручную изменил занятие. "
            "Такие занятия не пересоздаются при смене шаблона."
        ),
    )
    cancel_reason = models.TextField(_("Причина отмены"), blank=True)
    note = models.TextField(_("Примечание"), blank=True)

    class Meta:
        verbose_name = _("Занятие")
        verbose_name_plural = _("Занятия")
        ordering = ["starts_at"]
        indexes = [
            models.Index(fields=["group", "starts_at"]),
            models.Index(fields=["teacher", "starts_at"]),
            models.Index(fields=["organization", "starts_at"]),
            models.Index(fields=["organization", "status", "starts_at"]),
        ]

    def __str__(self):
        return f"{self.group or 'Индив.'} — {self.starts_at:%d.%m %H:%M}"

    def transition_to(self, new_status: str):
        allowed = ALLOWED_STATUS_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise ValidationError(
                _(
                    f"Переход из '{self.status}' в '{new_status}' недопустим. "
                    f"Допустимые переходы: {', '.join(allowed) or 'нет'}."
                )
            )
        self.status = new_status
        self.save(update_fields=["status", "updated_at"])

    def reschedule_to(self, new_lesson: "Lesson"):
        self.transition_to(self.Status.RESCHEDULED)
        new_lesson.rescheduled_from = self
        new_lesson.save(update_fields=["rescheduled_from", "updated_at"])
        return new_lesson
