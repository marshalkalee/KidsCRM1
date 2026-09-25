from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from domains.platform.core.models import TenantModel


class Attendance(TenantModel):
    """Занятие × ребёнок (ТЗ п. 3.1) — контракт №1 из TRU-8 со стороны
    потребителя (SubscriptionService, домен money.subscriptions). Факт
    списания хранится здесь (consumed_from_subscription/subscription_id),
    а не только в LessonConsumption — остаток всегда можно пересчитать из
    первичных данных (ТЗ п. 3.2), и посещаемость видна независимо от того,
    заглянули мы в биллинг или нет.

    Единственная точка входа для смены статуса — Attendance.mark(), не
    прямое присвоение status: только через неё гарантированно вызывается
    SubscriptionService.consume()/revert() (иначе списание с абонементом
    разойдётся с фактической посещаемостью)."""

    class Status(models.TextChoices):
        PRESENT = "present", _("Был")
        ABSENT = "absent", _("Не был")
        MAKEUP = "makeup", _("Отработка")

    class AbsenceReason(models.TextChoices):
        ILLNESS = "illness", _("Болезнь")
        FAMILY = "family", _("Семейные обстоятельства")
        NO_REASON = "no_reason", _("Без причины")

    lesson = models.ForeignKey(
        "schedule.Lesson", on_delete=models.CASCADE, related_name="attendances"
    )
    child = models.ForeignKey("clients.Child", on_delete=models.CASCADE, related_name="attendances")
    status = models.CharField(max_length=16, choices=Status.choices)
    absence_reason = models.CharField(
        max_length=16, choices=AbsenceReason.choices, blank=True, default=""
    )

    # Факт списания — источник правды для UI и для сверки (ТЗ п. 3.2).
    # subscription_id — обычный UUID, не FK: домен посещаемости (scheduling)
    # не должен зависеть от домена money, тот же принцип, что у
    # LessonConsumption.lesson_id в money.subscriptions.
    consumed_from_subscription = models.BooleanField(default=False)
    subscription_id = models.UUIDField(null=True, blank=True)
    # Последний исход SubscriptionService.consume() — для диагностики
    # (почему не списалось), значения ConsumeOutcome. Пусто, пока не был
    # ни разу отмечен «пришёл».
    consume_outcome = models.CharField(max_length=32, blank=True, default="")
    # «Нет активного абонемента» — единственный исход, требующий действия
    # администратора (ТЗ п. 4.3): остальные (заморожен/исчерпан/правило
    # запрещает) — ожидаемые состояния биллинга, не повод дёргать админа.
    no_subscription_flag = models.BooleanField(default=False)

    marked_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    marked_at = models.DateTimeField(null=True, blank=True)
    # TRU-52: правку отметки за занятие, которое уже прошло (не первую
    # отметку сразу после урока, а именно повторное изменение), нужно
    # уметь показать в журнале отдельно от обычных отметок (ТЗ п. 4.3,
    # 11.8) — ставится один раз в Attendance.mark() и не снимается: это
    # исторический факт об этой записи, а не текущее состояние.
    is_retroactive_edit = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["lesson", "child"], name="unique_attendance_per_lesson_child"
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.organization_id:
            self.organization_id = self.lesson.organization_id
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.child} — {self.lesson} — {self.get_status_display()}"

    def _resolve_direction_id(self):
        """direction_id обязателен для SubscriptionService.consume()
        (несколько абонементов ребёнка на разные направления — иначе не
        выбрать, какой списывать). У группового занятия направление берётся
        от группы; у индивидуального (TRU-47, Lesson.group=None) такого
        поля нет — берём первое направление ребёнка. При нескольких
        направлениях у ребёнка на индивидуальных занятиях это неоднозначно;
        закрывать это добавлением direction на Lesson — отдельная задача,
        не TRU-50. Нет ни одного направления — списывать не от чего."""
        if self.lesson.group_id:
            return self.lesson.group.direction_id
        return self.child.directions.values_list("id", flat=True).first()

    def mark(self, status, *, actor, absence_reason=""):
        from domains.platform.core.audit import AuditLog

        if status not in Attendance.Status.values:
            raise ValueError(f"Неизвестный статус посещаемости: {status}")

        new_absence_reason = absence_reason if status == Attendance.Status.ABSENT else ""
        before = {
            "status": self.status,
            "absence_reason": self.absence_reason,
            "consumed_from_subscription": self.consumed_from_subscription,
        }

        # TRU-52: это правка (не первая отметка) занятия, которое уже
        # прошло — не совпадает с обычным сценарием «отметили сразу после
        # урока» (тогда marked_at ещё None). Совпадение значений — не
        # правка (повторный клик по той же кнопке), флаг не ставим.
        is_edit = self.marked_at is not None and (
            self.status != status or self.absence_reason != new_absence_reason
        )
        if is_edit and self._lesson_already_happened():
            self.is_retroactive_edit = True

        if status == Attendance.Status.PRESENT:
            self._consume()
        else:
            self._revert()
        self.absence_reason = new_absence_reason

        self.status = status
        self.marked_by = actor
        self.marked_at = timezone.now()
        self.save()

        AuditLog.record(
            actor=actor,
            action=AuditLog.Action.MARK_ATTENDANCE,
            entity=self,
            before=before,
            after={
                "status": self.status,
                "absence_reason": self.absence_reason,
                "consumed_from_subscription": self.consumed_from_subscription,
                "no_subscription_flag": self.no_subscription_flag,
                "is_retroactive_edit": self.is_retroactive_edit,
            },
        )
        return self

    def _lesson_already_happened(self):
        tz = timezone.zoneinfo.ZoneInfo(self.organization.timezone or "Asia/Almaty")
        today = timezone.now().astimezone(tz).date()
        lesson_date = self.lesson.starts_at.astimezone(tz).date()
        return lesson_date < today

    def _consume(self):
        """Списание при отметке «пришёл». SubscriptionService.consume()
        сам идемпотентен по паре (child, lesson) — повторный вызов (в т.ч.
        после был→не был→снова был) не плодит второе списание, поэтому
        здесь можно звать его безусловно, не проверяя свой собственный
        consumed_from_subscription."""
        from domains.money.subscriptions.subscription_service import (
            ConsumeOutcome,
            SubscriptionService,
        )

        direction_id = self._resolve_direction_id()
        if direction_id is None:
            # Нет направления — некуда посмотреть абонемент; для потребителя
            # (админа) неотличимо от «нет активного абонемента» — то же
            # действие: флаг + автозадача.
            self.consumed_from_subscription = False
            self.subscription_id = None
            self.consume_outcome = ConsumeOutcome.NO_ACTIVE_SUBSCRIPTION.value
            self.no_subscription_flag = True
            self._notify_missing_subscription()
            return

        result = SubscriptionService.consume(
            child_id=self.child_id, lesson_id=self.lesson_id, direction_id=direction_id
        )
        self.consumed_from_subscription = result.outcome == ConsumeOutcome.CONSUMED
        self.subscription_id = result.subscription_id
        self.consume_outcome = result.outcome.value
        self.no_subscription_flag = result.outcome == ConsumeOutcome.NO_ACTIVE_SUBSCRIPTION
        if self.no_subscription_flag:
            self._notify_missing_subscription()

    def _revert(self):
        """Откат при уходе со статуса «пришёл» (не был/отработка).
        SubscriptionService.revert() идемпотентен — если списания не было
        (ребёнка отметили «не был» без предварительного «пришёл»), просто
        ничего не делает."""
        from domains.money.subscriptions.subscription_service import SubscriptionService

        SubscriptionService.revert(child_id=self.child_id, lesson_id=self.lesson_id)
        self.consumed_from_subscription = False
        self.subscription_id = None
        self.consume_outcome = ""
        self.no_subscription_flag = False

    def _notify_missing_subscription(self):
        """M1 (согласовано в TRU-50): саму модель Task и её обработку
        делает Bekzat в M2 (domains.platform.tasks — пока пустой каркас).
        Вызов уже происходит из правильного места — этот стык не потеряется
        при передаче; создание реальной Task — заглушка, безопасно
        заменяемая в M2 без изменений здесь."""
        from domains.platform.tasks.services import create_admin_task_for_missing_subscription

        create_admin_task_for_missing_subscription(attendance=self)
