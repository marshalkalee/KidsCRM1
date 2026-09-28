"""
Заявки воронки продаж (ТЗ п. 5.1, п. 3.1 Lead; TRU-99).

Заявка — контакт, который ещё не стал клиентом: родитель позвонил,
написал в Instagram, оставил номер на сайте. Статусы — фиксированный
набор MVP (кастомизация — V2): так проще и код, и аналитика конверсии.

Каждая смена статуса пишется в LeadStatusChange: из какого, в какой, кто,
когда. Из этой истории в M3 считается конверсия по этапам — по одному
текущему статусу её уже не восстановить.

Справочники LeadSource и LeadRejectionReason — здесь же: без них не
сохранить заявку. Управление ими, архивация и значения по умолчанию —
TRU-93.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from domains.platform.core.models import TenantModel, UUIDPrimaryKeyModel
from domains.platform.core.phone import normalize_phone_number


class LeadDictionary(TenantModel):
    """
    Редактируемый справочник организации. Значения не удаляются, а
    архивируются (is_active=False): в старых заявках они должны остаться
    видны, а в новых — не предлагаться.
    """

    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class LeadSource(LeadDictionary):
    """Откуда пришла заявка: Instagram, WhatsApp, сайт, звонок, рекомендация…"""


class LeadRejectionReason(LeadDictionary):
    """Почему отказались: дорого, неудобное время, далеко…"""


class Lead(TenantModel):
    class Status(models.TextChoices):
        NEW = "new", "Новая"
        CONTACTED = "contacted", "Связались"
        TRIAL_SCHEDULED = "trial_scheduled", "Записан на пробное"
        TRIAL_ATTENDED = "trial_attended", "Пришёл на пробное"
        PURCHASED = "purchased", "Купил абонемент"
        THINKING = "thinking", "Думает"
        REJECTED = "rejected", "Отказ"

    # Куда можно перейти из каждого статуса. Назад по воронке можно там,
    # где это бывает в жизни: не дошёл до пробного — снова «Связались»,
    # передумал после отказа — заявку возвращают в работу. «Купил» —
    # конец пути: дальше это уже клиент (конвертация — TRU-102).
    TRANSITIONS = {
        Status.NEW: {Status.CONTACTED, Status.TRIAL_SCHEDULED, Status.THINKING, Status.REJECTED},
        Status.CONTACTED: {
            Status.TRIAL_SCHEDULED,
            Status.PURCHASED,
            Status.THINKING,
            Status.REJECTED,
        },
        Status.TRIAL_SCHEDULED: {
            Status.TRIAL_ATTENDED,
            Status.CONTACTED,
            Status.THINKING,
            Status.REJECTED,
        },
        Status.TRIAL_ATTENDED: {
            Status.PURCHASED,
            Status.TRIAL_SCHEDULED,
            Status.THINKING,
            Status.REJECTED,
        },
        Status.THINKING: {
            Status.CONTACTED,
            Status.TRIAL_SCHEDULED,
            Status.PURCHASED,
            Status.REJECTED,
        },
        Status.REJECTED: {Status.CONTACTED},
        Status.PURCHASED: set(),
    }

    branch = models.ForeignKey(
        "tenants.Branch", on_delete=models.PROTECT, null=True, blank=True, related_name="leads"
    )
    parent_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20)
    child_name = models.CharField(max_length=255, blank=True)
    child_age = models.PositiveSmallIntegerField(null=True, blank=True)
    direction = models.ForeignKey(
        "tenants.Direction", on_delete=models.PROTECT, null=True, blank=True, related_name="leads"
    )
    source = models.ForeignKey(
        LeadSource, on_delete=models.PROTECT, null=True, blank=True, related_name="leads"
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_leads",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    # Когда заявка попала в текущий статус — для «висит N дней» на доске
    # без подзапроса к истории на каждую карточку.
    status_changed_at = models.DateTimeField(default=timezone.now)
    rejection_reason = models.ForeignKey(
        LeadRejectionReason, on_delete=models.PROTECT, null=True, blank=True, related_name="leads"
    )
    rejection_comment = models.TextField(blank=True)
    # Заполняется при конвертации в клиента (TRU-102).
    converted_child = models.ForeignKey(
        "clients.Child", on_delete=models.SET_NULL, null=True, blank=True, related_name="leads"
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["organization", "phone"]),
        ]

    def __str__(self) -> str:
        return f"{self.parent_name} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        self.phone = normalize_phone_number(self.phone)
        super().save(*args, **kwargs)

    def can_move_to(self, status) -> bool:
        return status in self.TRANSITIONS[self.status]


class LeadStatusChange(UUIDPrimaryKeyModel):
    """
    Одна смена статуса. Только добавляется — ни правки, ни удаления: это
    сырьё для аналитики конверсии. Создание заявки — тоже запись
    (from_status пустой), чтобы этап «заявка» был в истории с временем.
    """

    organization = models.ForeignKey("tenants.Organization", on_delete=models.PROTECT)
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="status_changes")
    from_status = models.CharField(max_length=20, choices=Lead.Status.choices, blank=True)
    to_status = models.CharField(max_length=20, choices=Lead.Status.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    changed_at = models.DateTimeField(default=timezone.now)
    rejection_reason = models.ForeignKey(
        LeadRejectionReason, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    comment = models.TextField(blank=True)

    class Meta:
        ordering = ["changed_at"]
        indexes = [models.Index(fields=["organization", "to_status", "changed_at"])]

    def save(self, *args, **kwargs):
        if self.pk and LeadStatusChange.objects.filter(pk=self.pk).exists():
            raise PermissionError("Историю статусов заявки нельзя редактировать.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Историю статусов заявки нельзя удалять.")


class LeadComment(TenantModel):
    """Лента комментариев заявки: пишется после каждого контакта."""

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    text = models.TextField()

    class Meta:
        ordering = ["created_at"]
