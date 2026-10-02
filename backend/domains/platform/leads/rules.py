"""Автоправило: заявка без движения N дней → задача ответственному
«перезвонить» (ТЗ п. 5.2, TRU-108). Идемпотентность — через source_key
на Task: уникален, пока задача открыта."""

from django.utils import timezone

from domains.platform.tasks.models import RuleRun, Task
from domains.platform.tasks.services import create_task
from domains.platform.tenants.models import Organization
from domains.platform.tenants.org_settings import (
    LEAD_STALE_DAYS_THRESHOLD,
    RULE_LEAD_STALE_ENABLED,
    get_org_setting,
)

from .models import Lead

STALE_STATUSES = [Lead.Status.NEW, Lead.Status.CONTACTED, Lead.Status.THINKING]


def create_tasks_for_stale_leads() -> int:
    created = 0
    for organization in Organization.objects.all():
        if not get_org_setting(organization, RULE_LEAD_STALE_ENABLED):
            continue
        threshold_days = get_org_setting(organization, LEAD_STALE_DAYS_THRESHOLD)
        cutoff = timezone.now() - timezone.timedelta(days=threshold_days)
        stale_leads = Lead.objects.for_tenant(organization).filter(
            status__in=STALE_STATUSES,
            status_changed_at__lte=cutoff,
            assigned_to__isnull=False,
        )
        created_for_org = 0
        for lead in stale_leads:
            task = create_task(
                type=Task.Type.CALL_BACK,
                assignee=lead.assigned_to,
                due_date=None,
                subject=f"Перезвонить: {lead.parent_name}",
                organization=organization,
                source=Task.Source.AUTO,
                branch=lead.branch,
                lead=lead,
                source_key=f"lead_stale:{lead.id}",
            )
            if task is not None:
                created_for_org += 1
        if created_for_org:
            RuleRun.objects.create(
                organization=organization, rule="lead_stale", tasks_created=created_for_org
            )
        created += created_for_org
    return created
