"""
Кабинет родителя (M4): вход по коду из SMS/Telegram, без пароля (TRU-135).

Родитель — не сотрудник: у него нет User, нет JWT и роли в организации.
Его «аккаунт» — номер телефона. Какие дети ему видны, считается на каждом
запросе из контактов детей (ChildContact) с этим номером — отвязали
контакт в карточке ребёнка, и доступ к ребёнку пропал сразу, без
отзыва сессий (portal/access.py).

ParentAccount не привязан к организации: один номер — один вход, даже
если дети ходят в разные центры на платформе.
"""

from django.conf import settings
from django.db import models

from domains.platform.core.models import TenantModel, UUIDPrimaryKeyModel


class ParentAccount(UUIDPrimaryKeyModel):
    phone = models.CharField(max_length=20, unique=True)
    language = models.CharField(max_length=5, default="ru")
    created_at = models.DateTimeField(auto_now_add=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    # DRF ждёт у request.user эти признаки.
    is_authenticated = True
    is_anonymous = False

    def __str__(self) -> str:
        return self.phone


class OtpChallenge(UUIDPrimaryKeyModel):
    """Один запрошенный код. Сам код не хранится — только HMAC от него.
    Строка создаётся и для номера, которого нет в базе (код никуда не
    уходит): лимиты и ответы одинаковы, по ним не понять, есть ли номер."""

    class Purpose(models.TextChoices):
        LOGIN = "login", "Вход"
        PHONE_CHANGE = "phone_change", "Смена телефона"

    phone = models.CharField(max_length=20)
    purpose = models.CharField(max_length=20, choices=Purpose.choices, default=Purpose.LOGIN)
    # Для смены телефона — чей номер меняется.
    account = models.ForeignKey(
        ParentAccount, on_delete=models.CASCADE, null=True, blank=True, related_name="challenges"
    )
    code_hash = models.CharField(max_length=64)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used_at = models.DateTimeField(null=True, blank=True)
    channel = models.CharField(max_length=20, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["phone", "-created_at"]),
            models.Index(fields=["ip", "-created_at"]),
        ]


class ParentSession(UUIDPrimaryKeyModel):
    """Устройство, на котором родитель вошёл. Токен хранится хэшем; срок
    продлевается при использовании (не входить заново каждую неделю), а
    «Выйти на всех устройствах» отзывает все."""

    account = models.ForeignKey(ParentAccount, on_delete=models.CASCADE, related_name="sessions")
    token_hash = models.CharField(max_length=64, unique=True)
    user_agent = models.CharField(max_length=255, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-last_seen_at"]


class ParentLessonRequest(TenantModel):
    """Запрос родителя на изменение участия ребёнка в занятии (TRU-143).

    Сам запрос намеренно не меняет состав занятия. Запись или отмена
    выполняется сотрудником отдельным процессом обработки (TRU-146).
    """

    class Type(models.TextChoices):
        ENROLL = "enroll", "Запись"
        CANCEL = "cancel", "Отмена"

    class Kind(models.TextChoices):
        REGULAR = "regular", "Обычное занятие"
        MAKEUP = "makeup", "Отработка"

    class Status(models.TextChoices):
        NEW = "new", "Новый"
        APPROVED = "approved", "Одобрен"
        REJECTED = "rejected", "Отклонён"

    class CancelReason(models.TextChoices):
        ILLNESS = "illness", "Болезнь"
        FAMILY = "family", "Семейные обстоятельства"
        OTHER = "other", "Другое"

    requested_by = models.ForeignKey(
        ParentAccount, on_delete=models.PROTECT, related_name="lesson_requests"
    )
    child = models.ForeignKey(
        "clients.Child", on_delete=models.PROTECT, related_name="parent_lesson_requests"
    )
    lesson = models.ForeignKey(
        "schedule.Lesson", on_delete=models.PROTECT, related_name="parent_requests"
    )
    type = models.CharField(max_length=10, choices=Type.choices)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.REGULAR)
    comment = models.TextField(blank=True)
    cancel_reason = models.CharField(
        max_length=16, choices=CancelReason.choices, blank=True, default=""
    )
    notice_hours_required = models.PositiveSmallIntegerField(null=True, blank=True)
    notice_is_timely = models.BooleanField(null=True, blank=True)
    will_be_charged = models.BooleanField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.NEW)
    source_attendance = models.ForeignKey(
        "attendance.Attendance",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="parent_makeup_requests",
    )
    spots_available_at_request = models.PositiveSmallIntegerField(null=True, blank=True)
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="processed_parent_lesson_requests",
    )
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "status", "-created_at"]),
            models.Index(fields=["organization", "child", "-created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "child", "lesson", "type", "kind"],
                condition=models.Q(status="new", deleted_at__isnull=True),
                name="unique_open_parent_lesson_request",
            ),
            models.UniqueConstraint(
                fields=["organization", "source_attendance"],
                condition=models.Q(
                    status="new", source_attendance__isnull=False, deleted_at__isnull=True
                ),
                name="unique_open_parent_makeup_source",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(kind="makeup", type="enroll", source_attendance__isnull=False)
                    | models.Q(kind="regular", source_attendance__isnull=True)
                ),
                name="valid_parent_request_source",
            ),
        ]

    def __str__(self):
        return f"{self.get_type_display()}: {self.child} — {self.lesson}"


class ParentAccessLog(models.Model):
    """Журнал входов кабинета — и неудачных, и по номерам, которых нет в
    базе. Успешный вход дополнительно пишется в AuditLog каждой
    организации, где у родителя есть дети (его видят сотрудники центра)."""

    class Event(models.TextChoices):
        CODE_REQUESTED = "code_requested", "Запрошен код"
        CODE_RATE_LIMITED = "code_rate_limited", "Слишком много запросов кода"
        LOGIN = "login", "Вход"
        LOGIN_FAILED = "login_failed", "Неверный код"
        LOGOUT = "logout", "Выход"
        LOGOUT_ALL = "logout_all", "Выход на всех устройствах"
        PHONE_CHANGED = "phone_changed", "Сменил телефон"
        DATA_VIEW = "data_view", "Смотрел данные"

    account = models.ForeignKey(
        ParentAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name="access_log"
    )
    phone = models.CharField(max_length=20)
    event = models.CharField(max_length=30, choices=Event.choices)
    # Для DATA_VIEW — какой адрес кабинета запрошен (чей ребёнок, какой раздел).
    path = models.CharField(max_length=255, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["phone", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.get_event_display()} {self.phone}"


class Announcement(TenantModel):
    """Объявление центра для родителей (TRU-140): концерт, праздничное
    расписание, сбор на костюмы. Адресат — вся организация, филиал,
    направление или группа; кому именно видно — portal/announcements.py.
    Живёт в кабинете; рассылка в WhatsApp — V3 (ТЗ п. 4.5)."""

    class Audience(models.TextChoices):
        ORGANIZATION = "organization", "Весь центр"
        BRANCH = "branch", "Филиал"
        DIRECTION = "direction", "Направление"
        GROUP = "group", "Группа"

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        PUBLISHED = "published", "Опубликовано"

    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    published_at = models.DateTimeField(null=True, blank=True)
    # После этой даты объявление уходит из активных в архив кабинета.
    expires_on = models.DateField(null=True, blank=True)
    audience = models.CharField(
        max_length=15, choices=Audience.choices, default=Audience.ORGANIZATION
    )
    branch = models.ForeignKey(
        "tenants.Branch", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    direction = models.ForeignKey(
        "tenants.Direction", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    group = models.ForeignKey(
        "groups.Group", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    attachment_url = models.URLField(max_length=500, blank=True)
    attachment_name = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["-published_at", "-created_at"]
        indexes = [models.Index(fields=["organization", "status", "-published_at"])]

    def __str__(self) -> str:
        return self.title


class AnnouncementRead(models.Model):
    """Родитель открыл объявление — для пометки «непрочитанные»."""

    account = models.ForeignKey(ParentAccount, on_delete=models.CASCADE, related_name="reads")
    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE, related_name="reads")
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["account", "announcement"], name="unique_announcement_read"
            )
        ]

    def __str__(self) -> str:
        return f"{self.account} — {self.announcement}"


class ParentNoteRead(models.Model):
    """A parent account has opened a teacher note addressed to its child."""

    account = models.ForeignKey(ParentAccount, on_delete=models.CASCADE, related_name="note_reads")
    note = models.ForeignKey(
        "attendance.ParentNote", on_delete=models.CASCADE, related_name="parent_reads"
    )
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["account", "note"], name="unique_parent_note_read")
        ]

    def __str__(self) -> str:
        return f"{self.account} — {self.note}"
