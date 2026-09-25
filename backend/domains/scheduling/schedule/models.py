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
    # TRU-47: у индивидуального занятия (group=None) нет группового членства,
    # откуда обычно берутся участники — ребёнок(и) привязываются к самому
    # занятию напрямую. У группового занятия остаётся пусто — участники
    # берутся из Group.memberships, как и раньше (см. Lesson.participants).
    individual_children = models.ManyToManyField(
        "clients.Child",
        related_name="individual_lessons",
        verbose_name=_("Дети (индивидуальное занятие)"),
        blank=True,
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

    class CancelReasonCategory(models.TextChoices):
        TEACHER_ILLNESS = "teacher_illness", _("Болезнь преподавателя")
        HOLIDAY = "holiday", _("Праздник")
        ROOM_INCIDENT = "room_incident", _("Авария в помещении")
        OTHER = "other", _("Другое")

    # TRU-48: справочник причин отмены — обязателен при отмене (проверяется
    # во view/сериализаторе, не здесь, т.к. пустое значение допустимо для
    # всех остальных статусов). cancel_reason остаётся свободным
    # комментарием — обязателен только когда category=OTHER.
    cancel_reason_category = models.CharField(
        _("Причина отмены (категория)"),
        max_length=32,
        choices=CancelReasonCategory.choices,
        blank=True,
    )
    cancel_reason = models.TextField(_("Причина отмены (комментарий)"), blank=True)
    note = models.TextField(_("Примечание"), blank=True)

    class Meta:
        verbose_name = _("Занятие")
        verbose_name_plural = _("Занятия")
        ordering = ["starts_at"]
        indexes = [
            models.Index(fields=["group", "starts_at"]),
            models.Index(fields=["teacher", "starts_at"]),
            # Для conflicts.find_conflicting_lessons (TRU-46) — запрос по
            # залу + пересечению времени должен идти по индексу, не сканом.
            models.Index(fields=["room", "starts_at"]),
            models.Index(fields=["organization", "starts_at"]),
            models.Index(fields=["organization", "status", "starts_at"]),
        ]

    def __str__(self):
        return f"{self.group or 'Индив.'} — {self.starts_at:%d.%m %H:%M}"

    @property
    def is_individual(self):
        return self.group_id is None

    def participants(self):
        """Дети, которые должны быть на занятии — общий интерфейс
        независимо от того, групповое занятие или индивидуальное (TRU-47),
        чтобы экран посещаемости (TRU-56) не разветвлялся по типу занятия.
        Групповое — активные на сейчас участники группы (left_at=None);
        индивидуальное — individual_children напрямую. Плюс в обоих
        случаях — записанные «поверх» (LessonEnrollment, TRU-53: отработки
        и пробные) с активной записью (cancelled_at=None). Единый источник
        специально: если список участников занятия собирать по-разному в
        разных местах (посещаемость, контроль вместимости, отмена/перенос),
        они разойдутся — см. описание TRU-53."""
        from domains.people.clients.models import Child

        if self.group_id:
            base_ids = Child.objects.filter(
                group_memberships__group_id=self.group_id,
                group_memberships__left_at__isnull=True,
            ).values_list("id", flat=True)
        else:
            base_ids = self.individual_children.values_list("id", flat=True)

        enrolled_ids = self.enrollments.filter(cancelled_at__isnull=True).values_list(
            "child_id", flat=True
        )
        return Child.objects.filter(
            models.Q(id__in=base_ids) | models.Q(id__in=enrolled_ids)
        ).distinct()

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

    def reschedule_to(self, new_lesson: "Lesson", *, actor=None):
        """Перенос — по ТЗ п. 4.2 это "отмена с причиной + создание нового
        со связью" (TRU-49): исходное занятие получает статус «перенесено»,
        новое хранит ссылку на него в обе стороны (rescheduled_from/
        rescheduled_to). Списания с абонемента участников исходного занятия
        откатываются той же логикой, что при обычной отмене (TRU-48,
        согласовано с Bekzat) — SubscriptionService.revert() идемпотентен,
        для обычного переноса в будущем просто ничего не делает."""
        from domains.money.subscriptions.subscription_service import SubscriptionService
        from domains.platform.core.audit import AuditLog

        before = {"status": self.status}

        self.transition_to(self.Status.RESCHEDULED)
        new_lesson.rescheduled_from = self
        new_lesson.save(update_fields=["rescheduled_from", "updated_at"])

        for child in self.participants():
            SubscriptionService.revert(child_id=child.id, lesson_id=self.id)

        AuditLog.record(
            actor=actor,
            action=AuditLog.Action.RESCHEDULE,
            entity=self,
            before=before,
            after={"status": self.status, "rescheduled_to_id": str(new_lesson.id)},
        )
        return new_lesson

    def cancel(self, *, actor, category: str, comment: str = ""):
        """Отмена с обязательной причиной (TRU-48, ТЗ п. 4.2/4.3).

        Занятие отменил центр — списание с абонемента не производится ни
        при каких условиях; если оно уже было списано (отмена задним
        числом — занятие в прошлом, посещаемость уже отмечена), откатываем
        его для каждого участника. SubscriptionService.revert() идемпотентен:
        если списания не было (обычный случай — занятие ещё в будущем),
        просто ничего не делает.

        Пишет запись в аудит-лог: кто отменил, когда, с какой причиной.
        """
        from domains.money.subscriptions.subscription_service import SubscriptionService
        from domains.platform.core.audit import AuditLog

        before = {
            "status": self.status,
            "cancel_reason_category": self.cancel_reason_category,
            "cancel_reason": self.cancel_reason,
        }

        self.transition_to(self.Status.CANCELLED)
        self.cancel_reason_category = category
        self.cancel_reason = comment
        self.is_modified = True
        self.save(
            update_fields=["cancel_reason_category", "cancel_reason", "is_modified", "updated_at"]
        )

        for child in self.participants():
            SubscriptionService.revert(child_id=child.id, lesson_id=self.id)

        AuditLog.record(
            actor=actor,
            action=AuditLog.Action.CANCEL,
            entity=self,
            before=before,
            after={
                "status": self.status,
                "cancel_reason_category": self.cancel_reason_category,
                "cancel_reason": self.cancel_reason,
            },
        )


class RescheduleCallLog(TenantModel):
    """
    TRU-49: кто уже обзвонён по переносу конкретного занятия — отметки
    должны сохраняться и быть видны при возврате на экран (критерий
    приёмки), а не жить только в состоянии фронтенда, иначе при двадцати
    детях администратор собьётся и кому-то позвонит дважды, а кому-то ни
    разу. Ключ — (занятие, контакт): один родитель с двумя детьми в одной
    группе отмечается один раз, не дважды.
    """

    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        related_name="reschedule_call_logs",
        verbose_name=_("Перенесённое занятие"),
    )
    parent_contact = models.ForeignKey(
        "clients.ParentContact",
        on_delete=models.CASCADE,
        related_name="reschedule_call_logs",
        verbose_name=_("Контакт"),
    )
    called_at = models.DateTimeField(auto_now_add=True)
    called_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = _("Отметка обзвона о переносе")
        verbose_name_plural = _("Отметки обзвона о переносе")
        constraints = [
            models.UniqueConstraint(
                fields=["lesson", "parent_contact"],
                name="unique_reschedule_call_per_contact",
            ),
        ]

    def save(self, *args, **kwargs):
        self.organization_id = self.lesson.organization_id
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.lesson_id} — {self.parent_contact_id}"


class LessonEnrollment(TenantModel):
    """Запись ребёнка на занятие «поверх» состава группы (TRU-53, контракт
    №3 из TRU-8) — один механизм для двух потребителей: отработка (ребёнок
    из другой группы отрабатывает пропуск, M1) и пробное занятие (ребёнок
    из заявки, ещё не студент, M2). Единственная точка входа —
    LessonService.enroll()/cancel_enrollment() (enrollment_service.py), не
    прямое создание — там же контроль вместимости и правило списания по
    типу. cancelled_at — мягкая отмена (не delete): история должна
    остаться, посещаемость по уже прошедшей записи не должна повиснуть
    без объяснения."""

    class Kind(models.TextChoices):
        MAKEUP = "makeup", _("Отработка")
        TRIAL = "trial", _("Пробное")

    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="enrollments")
    child = models.ForeignKey(
        "clients.Child", on_delete=models.CASCADE, related_name="lesson_enrollments"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    enrolled_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Запись поверх группы")
        verbose_name_plural = _("Записи поверх группы")
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["lesson", "child"],
                condition=models.Q(cancelled_at__isnull=True),
                name="unique_active_enrollment_per_lesson_child",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.organization_id:
            self.organization_id = self.lesson.organization_id
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.child} → {self.lesson} ({self.get_kind_display()})"
