"""
Бизнес-правила заявок (TRU-99): создание и смена статуса. API и будущие
точки входа (быстрая форма TRU-97, приём с сайта TRU-110, доска TRU-94)
вызывают эти функции, а не пишут в модель сами — так правило «отказ без
причины невозможен» и запись истории не обойти ни одним путём.
"""

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from domains.platform.users.models import User

from .models import Lead, LeadStatusChange

# Через сколько дней в статусе заявка «висит без движения» (TRU-94).
# Новая заявка без звонка сутки — уже потеря; «Думает» — дать неделю;
# «Записан на пробное» — пробное бывает через несколько дней. Закрытые
# статусы не залеживаются.
STALE_AFTER_DAYS = {
    Lead.Status.NEW: 1,
    Lead.Status.CONTACTED: 3,
    Lead.Status.TRIAL_SCHEDULED: 7,
    Lead.Status.TRIAL_ATTENDED: 2,
    Lead.Status.THINKING: 7,
}


class LeadTransitionError(ValueError):
    """Переход запрещён — сообщение показывается пользователю как есть."""


@transaction.atomic
def create_lead(*, organization, actor, **fields) -> Lead:
    now = timezone.now()
    lead = Lead.objects.create(
        organization=organization,
        status=Lead.Status.NEW,
        status_changed_at=now,
        **fields,
    )
    LeadStatusChange.objects.create(
        organization=organization,
        lead=lead,
        from_status="",
        to_status=Lead.Status.NEW,
        changed_by=actor,
        changed_at=now,
    )
    return lead


@transaction.atomic
def change_status(lead, *, to_status, actor, rejection_reason=None, comment="") -> Lead:
    # Блокировка строки: два администратора одновременно тянут карточку на
    # доске — второй увидит уже новый статус, а не перезапишет его.
    lead = Lead.objects.select_for_update().get(pk=lead.pk)
    if to_status not in Lead.Status.values:
        raise LeadTransitionError("Неизвестный статус.")
    if to_status == lead.status:
        raise LeadTransitionError("Заявка уже в этом статусе.")
    if not lead.can_move_to(to_status):
        raise LeadTransitionError(
            f"Из статуса «{lead.get_status_display()}» нельзя перейти "
            f"в «{Lead.Status(to_status).label}»."
        )
    if to_status == Lead.Status.REJECTED:
        if rejection_reason is None:
            raise LeadTransitionError("Укажите причину отказа.")
        if (
            rejection_reason.organization_id != lead.organization_id
            or not rejection_reason.is_active
        ):
            raise LeadTransitionError("Такой причины отказа нет.")
    elif rejection_reason is not None:
        raise LeadTransitionError("Причина нужна только при отказе.")

    now = timezone.now()
    LeadStatusChange.objects.create(
        organization=lead.organization,
        lead=lead,
        from_status=lead.status,
        to_status=to_status,
        changed_by=actor,
        changed_at=now,
        rejection_reason=rejection_reason,
        comment=comment,
    )
    lead.status = to_status
    lead.status_changed_at = now
    # Причина живёт на заявке, пока та в отказе; вернули в работу — причина
    # остаётся только в истории.
    lead.rejection_reason = rejection_reason
    lead.rejection_comment = comment if to_status == Lead.Status.REJECTED else ""
    lead.save(
        update_fields=[
            "status",
            "status_changed_at",
            "rejection_reason",
            "rejection_comment",
            "updated_at",
        ]
    )
    return lead


def visible_leads(user):
    """
    Заявки, которые видит сотрудник. Владелец — все. Управляющий и
    администратор с закреплёнными филиалами — заявки своих филиалов, заявки
    без филиала (ещё не распределены) и назначенные на него лично; без
    закреплённых филиалов — все (маленький центр, один филиал).
    """
    qs = Lead.objects.for_tenant(user.organization)
    if user.role == User.Role.OWNER:
        return qs
    branch_ids = list(user.branches.values_list("id", flat=True))
    if not branch_ids:
        return qs
    return qs.filter(Q(branch_id__in=branch_ids) | Q(branch__isnull=True) | Q(assigned_to=user))
