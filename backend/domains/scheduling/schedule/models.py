from django.db import models
from django.utils.translation import gettext_lazy as _

from domains.platform.core.models import TenantModel, TimestampedSoftDeleteModel


class Lesson(TenantModel, TimestampedSoftDeleteModel):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", _("Запланировано")
        COMPLETED = "completed", _("Проведено")
        CANCELLED = "cancelled", _("Отменено")

    group = models.ForeignKey(
        "groups.Group",
        on_delete=models.PROTECT,
        related_name="lessons",
        verbose_name=_("Группа"),
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
    starts_at = models.DateTimeField(_("Начало"))
    ends_at = models.DateTimeField(_("Конец"))
    status = models.CharField(
        _("Статус"),
        max_length=16,
        choices=Status.choices,
        default=Status.SCHEDULED,
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
        ]

    def __str__(self):
        return f"{self.group} — {self.starts_at:%d.%m %H:%M}"
