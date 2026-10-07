"""
Публичное API для тарифа Enterprise (TRU-176, docs/public-api.md).

Ключ — третий тип доступа рядом с JWT сотрудников и токеном кабинета
родителя. Хранится только хеш: сам ключ показывается один раз при выдаче.
Ключ не сильнее сотрудника: область (чтение / чтение и запись) и филиалы
задаются при выдаче, отзывается одним нажатием.
"""

import hashlib

from django.conf import settings
from django.db import models

from domains.platform.core.models import TenantModel, UUIDPrimaryKeyModel


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class ApiKey(TenantModel):
    class Scope(models.TextChoices):
        READ = "read", "Только чтение"
        READ_WRITE = "read_write", "Чтение и запись"

    name = models.CharField(max_length=100)
    # Начало ключа — чтобы узнать его в списке, не храня целиком.
    prefix = models.CharField(max_length=16, db_index=True)
    key_hash = models.CharField(max_length=64, unique=True)
    scope = models.CharField(max_length=16, choices=Scope.choices, default=Scope.READ)
    # Пусто — все филиалы центра.
    branches = models.ManyToManyField("tenants.Branch", blank=True, related_name="api_keys")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.prefix}…)"

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class ApiRequestLog(UUIDPrimaryKeyModel):
    """Журнал обращений по ключу: кто, когда, какой адрес, что ответили.
    Только добавление — для разбора проблем и аудита (ТЗ п. 2)."""

    organization = models.ForeignKey("tenants.Organization", on_delete=models.CASCADE)
    key = models.ForeignKey(ApiKey, on_delete=models.CASCADE, related_name="requests")
    method = models.CharField(max_length=8)
    path = models.CharField(max_length=255)
    status = models.PositiveSmallIntegerField()
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["organization", "-created_at"])]


class CenterProfile(TenantModel):
    """Публичный профиль центра для будущего каталога (TRU-179) — отдельно от
    рабочих полей CRM: что видит родитель в карточке центра. Пока не
    опубликован, в публичный срез не попадает ничего."""

    MAX_PHOTOS = 5

    description = models.TextField(blank=True)
    logo_url = models.URLField(max_length=500, blank=True)
    photo_urls = models.JSONField(default=list, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    instagram = models.CharField(max_length=100, blank=True)
    is_published = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization"], name="center_profile_one_per_org")
        ]

    def __str__(self) -> str:
        return f"Профиль {self.organization_id}"
