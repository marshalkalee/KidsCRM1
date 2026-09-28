from django.db.models.signals import post_save
from django.dispatch import receiver

from domains.platform.tenants.models import Organization

from .defaults import ensure_default_dictionaries


@receiver(post_save, sender=Organization, dispatch_uid="leads_default_dictionaries")
def create_default_dictionaries(sender, instance, created, raw=False, **kwargs):
    # raw — загрузка фикстур: справочники приедут из самих фикстур.
    if created and not raw:
        ensure_default_dictionaries(instance)
