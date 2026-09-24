"""
Общие абстрактные базовые классы — не бизнес-модель сама по себе, а
фундамент, на котором стоят бизнес-модели всех доменов (см. ADR-001 и
согласованную схему БД — backend/docs/db-schema-v1 на ветке
feature/db-schema-v1). Конкретные сущности (Organization, Branch, Child,
...) заводятся в отдельных задачах по доменам, не здесь.

Сквозные инварианты из db-schema-v1, зашитые в эти базовые классы:
- PK — UUID везде, не auto-increment integer.
- `organization_id` — обязателен на каждой бизнес-таблице.
- Soft delete везде — физического удаления нет (ТЗ п. 3.2).
- Все datetime — timestamptz (Django с USE_TZ=True хранит в UTC сам).
"""

import uuid

from django.db import models
from django.utils import timezone


class UUIDPrimaryKeyModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet):
    def alive(self):
        return self.filter(deleted_at__isnull=True)

    def dead(self):
        return self.filter(deleted_at__isnull=False)


class SoftDeleteManager(models.Manager):
    """Manager по умолчанию — скрывает мягко удалённые записи."""

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).alive()

    def all_with_deleted(self):
        return SoftDeleteQuerySet(self.model, using=self._db)


class TenantQuerySet(SoftDeleteQuerySet):
    def for_tenant(self, organization):
        return self.filter(organization=organization)


class TenantManager(models.Manager):
    def get_queryset(self):
        return TenantQuerySet(self.model, using=self._db).alive()

    def for_tenant(self, organization):
        return self.get_queryset().for_tenant(organization)

    def all_with_deleted(self):
        return TenantQuerySet(self.model, using=self._db)


class TimestampedSoftDeleteModel(UUIDPrimaryKeyModel):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False):
        """Soft delete — физическое удаление см. hard_delete()."""
        self.deleted_at = timezone.now()
        self.save(using=using, update_fields=["deleted_at"])

    def hard_delete(self, using=None, keep_parents=False):
        super().delete(using=using, keep_parents=keep_parents)


class TenantModel(TimestampedSoftDeleteModel):
    """
    Базовый класс для бизнес-моделей одной организации. `organization`
    хранится напрямую на каждой таблице (не через join) — так задумано в
    ADR-001 и db-schema-v1, чтобы `for_tenant()` не требовал JOIN на каждый
    запрос. Прямой `Model.objects.all()` в бизнес-коде запрещён — только
    `for_tenant(organization)`.
    """

    organization = models.ForeignKey("tenants.Organization", on_delete=models.PROTECT)

    objects = TenantManager()

    class Meta:
        abstract = True
