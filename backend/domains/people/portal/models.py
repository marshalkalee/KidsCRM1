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

from django.db import models

from domains.platform.core.models import UUIDPrimaryKeyModel


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

    account = models.ForeignKey(
        ParentAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name="access_log"
    )
    phone = models.CharField(max_length=20)
    event = models.CharField(max_length=30, choices=Event.choices)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["phone", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.get_event_display()} {self.phone}"
