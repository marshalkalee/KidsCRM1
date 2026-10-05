"""
Заявки воронки продаж (ТЗ п. 5.1, п. 3.1 Lead; TRU-99).

Заявка — контакт, который ещё не стал клиентом: родитель позвонил,
написал в Instagram, оставил номер на сайте. Статусы — фиксированный
набор MVP — системные роли, на которые опирается код и аналитика
конверсии. Центр настраивает поверх них свои этапы (LeadStage, TRU-154):
переименовывает, красит, переставляет и добавляет промежуточные, не меняя
смысла ролей.

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


class LeadKind(models.TextChoices):
    """
    Два вида продаж (TRU-98). Новая — контакт с улицы, проходит воронку с
    пробным. Продление — клиент уже свой: без пробного и источника, со
    своими причинами отказа. Смешивать нельзя — испортится конверсия:
    продления покажут 80% там, где у новых 20%.
    """

    NEW = "new", "Новая продажа"
    RENEWAL = "renewal", "Продление"


class LeadRejectionReason(LeadDictionary):
    """Почему отказались: дорого, неудобное время, далеко… У продлений —
    свой список (ушли из центра, переезд), поэтому причина знает свой вид."""

    kind = models.CharField(max_length=10, choices=LeadKind.choices, default=LeadKind.NEW)
    # «Не пришёл на пробное» — не возражение, а потерянный контакт (TRU-117):
    # отчёт по отказам считает такие отдельно. Признак, а не название —
    # центр может причину переименовать.
    is_lost_contact = models.BooleanField(default=False)


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

    # Продление (TRU-98): пробного нет — связались, думает, продлил или отказ.
    RENEWAL_STATUSES = [
        Status.NEW,
        Status.CONTACTED,
        Status.THINKING,
        Status.PURCHASED,
        Status.REJECTED,
    ]
    RENEWAL_TRANSITIONS = {
        Status.NEW: {Status.CONTACTED, Status.THINKING, Status.PURCHASED, Status.REJECTED},
        Status.CONTACTED: {Status.THINKING, Status.PURCHASED, Status.REJECTED},
        Status.THINKING: {Status.CONTACTED, Status.PURCHASED, Status.REJECTED},
        Status.REJECTED: {Status.CONTACTED},
        Status.PURCHASED: set(),
    }

    Kind = LeadKind

    kind = models.CharField(max_length=10, choices=LeadKind.choices, default=LeadKind.NEW)
    branch = models.ForeignKey(
        "tenants.Branch", on_delete=models.PROTECT, null=True, blank=True, related_name="leads"
    )
    # Продление — о каком клиенте (TRU-98). У новой заявки пусто.
    child = models.ForeignKey(
        "clients.Child",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="renewal_leads",
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
    # Этап центра (TRU-154): пусто — системный этап текущего статуса. Так
    # каждый путь, который меняет статус сам (сайт, пробные, продажа,
    # посещаемость), остаётся корректным, а свой этап появляется только
    # при явном переносе на него (services.move_to_stage).
    stage = models.ForeignKey(
        "LeadStage", on_delete=models.PROTECT, null=True, blank=True, related_name="leads"
    )
    rejection_reason = models.ForeignKey(
        LeadRejectionReason, on_delete=models.PROTECT, null=True, blank=True, related_name="leads"
    )
    rejection_comment = models.TextField(blank=True)
    # Заполняется при конвертации в клиента (TRU-102).
    converted_child = models.ForeignKey(
        "clients.Child", on_delete=models.SET_NULL, null=True, blank=True, related_name="leads"
    )
    # TRU-103: конкретный результат закрытия продажи. FK остаётся даже
    # после завершения воронки, чтобы из заявки всегда открыть именно тот
    # абонемент, который был продан в этом потоке.
    sold_subscription = models.ForeignKey(
        "subscriptions.Subscription",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_leads",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["organization", "kind", "status"]),
            models.Index(fields=["organization", "phone"]),
        ]

    def __str__(self) -> str:
        return f"{self.parent_name} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        self.phone = normalize_phone_number(self.phone)
        super().save(*args, **kwargs)

    @classmethod
    def transitions_for(cls, kind):
        return cls.RENEWAL_TRANSITIONS if kind == LeadKind.RENEWAL else cls.TRANSITIONS

    @classmethod
    def statuses_for(cls, kind):
        return cls.RENEWAL_STATUSES if kind == LeadKind.RENEWAL else cls.Status.values

    def can_move_to(self, status) -> bool:
        return status in self.transitions_for(self.kind).get(self.status, set())


class LeadStage(TenantModel):
    """
    Этап воронки центра (TRU-154, ТЗ п. 5.1 [V2]). Код и аналитика опираются
    на роль (Lead.Status), а не на название: у каждой роли ровно один
    системный этап (is_system) — его можно переименовать, перекрасить и
    переставить, но не скрыть. Свои этапы центр добавляет только внутри
    ролей «в работе» (CUSTOM_ROLES) — например «Тестирование уровня»
    между «Связались» и пробным; исходы («Купил», «Отказ») остаются
    системными, иначе конвертация и отчёт по отказам перестанут понимать,
    что произошло.

    Удалить этап с заявками или историей нельзя — только скрыть (ТЗ п. 3.2).
    """

    CUSTOM_ROLES = (
        Lead.Status.NEW,
        Lead.Status.CONTACTED,
        Lead.Status.TRIAL_SCHEDULED,
        Lead.Status.TRIAL_ATTENDED,
        Lead.Status.THINKING,
    )

    class Color(models.TextChoices):
        BLUE = "blue", "Синий"
        RED = "red", "Красный"
        AMBER = "amber", "Жёлтый"
        VIOLET = "violet", "Фиолетовый"
        GREEN = "green", "Зелёный"
        GRAY = "gray", "Серый"
        PINK = "pink", "Розовый"
        TEAL = "teal", "Бирюзовый"

    name = models.CharField(max_length=60)
    role = models.CharField(max_length=20, choices=Lead.Status.choices)
    is_system = models.BooleanField(default=False)
    order = models.PositiveSmallIntegerField(default=0)
    color = models.CharField(max_length=10, choices=Color.choices, default=Color.GRAY)
    is_hidden = models.BooleanField(default=False)

    class Meta:
        ordering = ["order", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "role"],
                condition=models.Q(is_system=True),
                name="unique_system_stage_per_role",
            )
        ]

    def __str__(self) -> str:
        return self.name



class LeadStatusChange(UUIDPrimaryKeyModel):
    """
    Одна смена статуса. Только добавляется — ни правки, ни удаления: это
    сырьё для аналитики конверсии. Создание заявки — тоже запись
    (from_status пустой), чтобы этап «заявка» был в истории с временем.
    """

    class EventType(models.TextChoices):
        STATUS_CHANGE = "status_change", "Смена статуса"
        TRIAL_RESCHEDULED = "trial_rescheduled", "Пробное перенесено"
        # Перенос между этапами одной роли (TRU-154): статус тот же, поэтому
        # конверсия по ролям его не видит.
        STAGE_CHANGE = "stage_change", "Смена этапа"

    organization = models.ForeignKey("tenants.Organization", on_delete=models.PROTECT)
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="status_changes")
    from_status = models.CharField(max_length=20, choices=Lead.Status.choices, blank=True)
    to_status = models.CharField(max_length=20, choices=Lead.Status.choices)
    # Ссылка, а не текст: после переименования история читается новым
    # названием. Пусто — системный этап to_status (TRU-154).
    to_stage = models.ForeignKey(
        LeadStage, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    changed_at = models.DateTimeField(default=timezone.now)
    event_type = models.CharField(
        max_length=24,
        choices=EventType.choices,
        default=EventType.STATUS_CHANGE,
    )
    is_automatic = models.BooleanField(
        default=False,
        help_text="Переход выполнен системой по бизнес-событию, а не вручную в заявке.",
    )
    rejection_reason = models.ForeignKey(
        LeadRejectionReason,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="status_changes",
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
