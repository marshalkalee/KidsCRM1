"""Отмена оплаты сбрасывает кэш аналитики центра (TRU-123): отмена — мягкое
удаление, то есть сохранение с заполненным deleted_at."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from domains.money.payments.models import Payment

from .epoch import bump_epoch


@receiver(post_save, sender=Payment)
def payment_cancelled(sender, instance, **kwargs):
    if instance.deleted_at is not None:
        bump_epoch(instance.organization_id)
