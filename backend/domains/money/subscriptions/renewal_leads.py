"""
Автоправило «абонемент заканчивается → заявка-продление» (TRU-98, точка
вызова для автоправил TRU-108). Раз в день по каждому центру: на каждый
заканчивающийся абонемент — открытая заявка-продление в воронке
«Продления», чтобы администратор видел, кому звонить, не открывая
отдельный экран.

Не плодит дубли: открытое продление уже есть — create_renewal_lead вернёт
его; по этому абонементу продление уже заводили и закрыли (продлили или
отказались) — второй раз не заводим, иначе отказ «воскресал» бы каждое утро.
"""

from domains.platform.leads.models import Lead, LeadKind
from domains.platform.leads.services import RenewalError, create_renewal_lead
from domains.platform.tenants.models import Organization

from .renewals import expiring_subscriptions


def create_renewal_leads(organization, today=None) -> int:
    """Сколько заявок-продлений создано сейчас."""
    created = 0
    seen = set()
    subscriptions = expiring_subscriptions(organization, today=today).select_related(
        "child", "subscription_type_version"
    )
    for subscription in subscriptions:
        child = subscription.child
        if child.pk in seen:
            continue
        seen.add(child.pk)
        already = (
            Lead.objects.for_tenant(organization)
            .filter(
                kind=LeadKind.RENEWAL, child=child, created_at__date__gte=subscription.starts_on
            )
            .exists()
        )
        if already:
            continue
        comment = (
            f"Автоматически: абонемент «{subscription.subscription_type_version.name}» "
            f"заканчивается {subscription.ends_on:%d.%m.%Y}."
        )
        try:
            _lead, was_created = create_renewal_lead(child, actor=None, comment=comment)
        except RenewalError:
            # Нет телефона — звонить некому; ребёнок и так виден на экране «Продления».
            continue
        created += was_created
    return created


def create_renewal_leads_for_all() -> int:
    return sum(create_renewal_leads(org) for org in Organization.objects.all())
