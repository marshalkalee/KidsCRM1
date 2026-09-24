from django.db import models
from django.utils.translation import gettext_lazy as _

from domains.platform.core.models import TenantModel, TimestampedSoftDeleteModel


class ScheduleTemplate(TenantModel, TimestampedSoftDeleteModel):
    group = models.ForeignKey(
        "groups.Group",
        on_delete=models.CASCADE,
        related_name="schedule_templates",
        verbose_name=_("Группа"),
    )
    valid_from = models.DateField(_("Действует с"))
    valid_until = models.DateField(_("Действует до"), null=True, blank=True)
    generate_weeks_ahead = models.PositiveSmallIntegerField(
        _("Генерировать на N недель вперёд"),
        default=4,
    )
    note = models.TextField(_("Примечание"), blank=True)

    class Meta:
        verbose_name = _("Шаблон расписания")
        verbose_name_plural = _("Шаблоны расписания")
        ordering = ["-valid_from"]

    def __str__(self):
        return f"{self.group} c {self.valid_from}"

    @property
    def is_active(self):
        from django.utils import timezone

        today = timezone.localdate()
        if self.valid_from > today:
            return False
        if self.valid_until and self.valid_until < today:
            return False
        return True


class ScheduleTemplateSlot(TenantModel):
    class Weekday(models.IntegerChoices):
        MONDAY = 0, _("Понедельник")
        TUESDAY = 1, _("Вторник")
        WEDNESDAY = 2, _("Среда")
        THURSDAY = 3, _("Четверг")
        FRIDAY = 4, _("Пятница")
        SATURDAY = 5, _("Суббота")
        SUNDAY = 6, _("Воскресенье")

    template = models.ForeignKey(
        ScheduleTemplate,
        on_delete=models.CASCADE,
        related_name="slots",
        verbose_name=_("Шаблон"),
    )
    weekday = models.IntegerField(
        _("День недели"),
        choices=Weekday.choices,
    )
    start_time = models.TimeField(_("Время начала"))
    duration_minutes = models.PositiveSmallIntegerField(
        _("Длительность (мин)"),
        default=60,
    )
    room = models.ForeignKey(
        "tenants.Room",
        on_delete=models.PROTECT,
        related_name="schedule_slots",
        verbose_name=_("Зал"),
        null=True,
        blank=True,
    )
    teacher = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="schedule_slots",
        verbose_name=_("Преподаватель"),
        null=True,
        blank=True,
        limit_choices_to={"role": "teacher"},
    )

    class Meta:
        verbose_name = _("Слот расписания")
        verbose_name_plural = _("Слоты расписания")
        ordering = ["weekday", "start_time"]

    def __str__(self):
        return f"{self.get_weekday_display()} {self.start_time} — {self.template.group}"
