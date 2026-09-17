from django.db import models
from django.utils.translation import gettext_lazy as _

from domains.platform.core.models import TenantModel, TimestampedSoftDeleteModel


class Group(TenantModel, TimestampedSoftDeleteModel):
    class Status(models.TextChoices):
        ACTIVE = "active", _("Активна")
        PAUSED = "paused", _("Приостановлена")
        CLOSED = "closed", _("Закрыта")

    branch = models.ForeignKey(
        "tenants.Branch",
        on_delete=models.PROTECT,
        related_name="groups",
        verbose_name=_("Филиал"),
    )
    direction = models.ForeignKey(
        "tenants.Direction",
        on_delete=models.PROTECT,
        related_name="groups",
        verbose_name=_("Направление"),
    )
    name = models.CharField(_("Название"), max_length=120)
    teachers = models.ManyToManyField(
        "users.User",
        related_name="teaching_groups",
        verbose_name=_("Преподаватели"),
        limit_choices_to={"role": "teacher"},
        blank=True,
    )
    capacity = models.PositiveSmallIntegerField(_("Вместимость"))
    age_min = models.PositiveSmallIntegerField(_("Возраст от"), null=True, blank=True)
    age_max = models.PositiveSmallIntegerField(_("Возраст до"), null=True, blank=True)
    status = models.CharField(
        _("Статус"),
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    class Meta:
        verbose_name = _("Группа")
        verbose_name_plural = _("Группы")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.branch})"


class GroupMembership(TenantModel, TimestampedSoftDeleteModel):
    group = models.ForeignKey(
        Group,
        on_delete=models.PROTECT,
        related_name="memberships",
        verbose_name=_("Группа"),
    )
    child = models.ForeignKey(
        "clients.Child",
        on_delete=models.PROTECT,
        related_name="group_memberships",
        verbose_name=_("Ребёнок"),
    )
    joined_at = models.DateField(_("Дата вступления"))
    left_at = models.DateField(_("Дата выхода"), null=True, blank=True)
    note = models.TextField(_("Примечание"), blank=True)

    class Meta:
        verbose_name = _("Участие в группе")
        verbose_name_plural = _("Участие в группах")
        constraints = [
            models.UniqueConstraint(
                fields=["group", "child"],
                condition=models.Q(left_at__isnull=True),
                name="unique_active_membership",
            )
        ]

    def __str__(self):
        return f"{self.child} → {self.group}"

    @property
    def is_active(self):
        return self.left_at is None
