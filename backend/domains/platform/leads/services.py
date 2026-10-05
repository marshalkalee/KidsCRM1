"""
Бизнес-правила заявок (TRU-99): создание и смена статуса. API и будущие
точки входа (быстрая форма TRU-97, приём с сайта TRU-110, доска TRU-94)
вызывают эти функции, а не пишут в модель сами — так правило «отказ без
причины невозможен» и запись истории не обойти ни одним путём.
"""

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from domains.people.clients.models import ChildContact, ParentContact
from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number
from domains.platform.users.models import User

from .models import Lead, LeadKind, LeadStatusChange

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
def change_status(
    lead,
    *,
    to_status,
    actor,
    rejection_reason=None,
    comment="",
    is_automatic=False,
    to_stage=None,
) -> Lead:
    """to_stage — свой этап центра внутри to_status (TRU-154); без него
    заявка встаёт на системный этап роли."""
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
            or rejection_reason.kind != lead.kind
        ):
            raise LeadTransitionError("Такой причины отказа нет.")
    elif rejection_reason is not None:
        raise LeadTransitionError("Причина нужна только при отказе.")

    if to_stage is not None and (
        to_stage.role != to_status or to_stage.organization_id != lead.organization_id
    ):
        raise LeadTransitionError("Этап не относится к этому статусу.")
    custom_stage = to_stage if to_stage is not None and not to_stage.is_system else None
    now = timezone.now()
    LeadStatusChange.objects.create(
        organization=lead.organization,
        lead=lead,
        from_status=lead.status,
        to_status=to_status,
        to_stage=custom_stage,
        changed_by=actor,
        changed_at=now,
        is_automatic=is_automatic,
        rejection_reason=rejection_reason,
        comment=comment,
    )
    lead.status = to_status
    lead.stage = custom_stage
    lead.status_changed_at = now
    # Причина живёт на заявке, пока та в отказе; вернули в работу — причина
    # остаётся только в истории.
    lead.rejection_reason = rejection_reason
    lead.rejection_comment = comment if to_status == Lead.Status.REJECTED else ""
    lead.save(
        update_fields=[
            "status",
            "stage",
            "status_changed_at",
            "rejection_reason",
            "rejection_comment",
            "updated_at",
        ]
    )
    return lead


def _check_stage(lead, stage):
    if stage.organization_id != lead.organization_id:
        raise LeadTransitionError("Такого этапа нет.")
    if stage.is_hidden:
        raise LeadTransitionError(f"Этап «{stage.name}» скрыт — выберите другой.")
    if stage.role not in Lead.statuses_for(lead.kind):
        raise LeadTransitionError(f"Этап «{stage.name}» не для этого вида заявок.")


@transaction.atomic
def move_to_stage(lead, *, stage, actor, rejection_reason=None, comment="") -> Lead:
    """Перенос на этап центра (доска, кнопки в заявке; TRU-154). Другая
    роль — обычная смена статуса со всеми её правилами; та же роль —
    смена этапа: статус не меняется, в истории отдельное событие, чтобы
    конверсия по ролям его не считала."""
    _check_stage(lead, stage)
    lead = Lead.objects.select_for_update().get(pk=lead.pk)
    if stage.role != lead.status:
        return change_status(
            lead,
            to_status=stage.role,
            to_stage=stage,
            actor=actor,
            rejection_reason=rejection_reason,
            comment=comment,
        )
    current = lead.stage_id if lead.stage_id and not lead.stage.is_hidden else None
    target = None if stage.is_system else stage.pk
    if current == target:
        raise LeadTransitionError("Заявка уже на этом этапе.")
    if rejection_reason is not None:
        raise LeadTransitionError("Причина нужна только при отказе.")
    now = timezone.now()
    LeadStatusChange.objects.create(
        organization=lead.organization,
        lead=lead,
        from_status=lead.status,
        to_status=lead.status,
        to_stage=None if stage.is_system else stage,
        changed_by=actor,
        changed_at=now,
        event_type=LeadStatusChange.EventType.STAGE_CHANGE,
        comment=comment,
    )
    lead.stage = None if stage.is_system else stage
    lead.status_changed_at = now
    lead.save(update_fields=["stage", "status_changed_at", "updated_at"])
    return lead


def leave_hidden_stage(stage, *, actor) -> int:
    """Скрытый этап (TRU-154): его заявки переходят на системный этап
    той же роли — статус не меняется, переход виден в истории."""
    moved = 0
    for lead in Lead.objects.filter(organization=stage.organization, stage=stage):
        now = timezone.now()
        LeadStatusChange.objects.create(
            organization=lead.organization,
            lead=lead,
            from_status=lead.status,
            to_status=lead.status,
            changed_by=actor,
            changed_at=now,
            event_type=LeadStatusChange.EventType.STAGE_CHANGE,
            is_automatic=True,
            comment=f"Этап «{stage.name}» скрыт — заявка перенесена на основной этап.",
        )
        lead.stage = None
        lead.save(update_fields=["stage", "updated_at"])
        moved += 1
    return moved


@transaction.atomic
def mark_trial_attended(*, organization, lesson, child, actor) -> bool:
    """Перевести связанную заявку после фактического посещения пробного.

    Повторная отметка безопасна: заявка блокируется и история создаётся
    только при первом переходе из «Записан» в «Пришёл». Если менеджер уже
    вручную увёл заявку дальше по воронке, посещаемость этот выбор не
    перезаписывает.
    """
    # Локальный импорт не создаёт цикл services -> schedule -> leads:
    # модуль записи на пробное сам использует change_status из этого файла.
    from domains.scheduling.schedule.models import LessonEnrollment

    lead_id = (
        LessonEnrollment.objects.for_tenant(organization)
        .filter(
            lesson=lesson,
            child=child,
            kind=LessonEnrollment.Kind.TRIAL,
            source_lead__isnull=False,
            cancelled_at__isnull=True,
        )
        .values_list("source_lead_id", flat=True)
        .first()
    )
    if lead_id is None:
        return False

    lead = Lead.objects.select_for_update().get(pk=lead_id, organization=organization)
    if lead.status != Lead.Status.TRIAL_SCHEDULED:
        return False

    local_start = timezone.localtime(lesson.starts_at)
    lesson_name = lesson.group.name if lesson.group_id else "Индивидуальное занятие"
    actor_note = f" Отметку поставил: {actor.full_name}." if actor else ""
    change_status(
        lead,
        to_status=Lead.Status.TRIAL_ATTENDED,
        actor=None,
        is_automatic=True,
        comment=(
            "Автоматически по отметке посещаемости: "
            f"{lesson_name}, {local_start:%d.%m.%Y %H:%M}.{actor_note}"
        ),
    )
    return True


@transaction.atomic
def create_trial_no_show_follow_up(*, organization, lesson, child, attendance) -> bool:
    """Поставить ответственному задачу после неявки на пробное.

    Задача создаётся только пока заявка действительно находится на этапе
    «Записан на пробное». Более поздний ручной статус (включая покупку)
    не меняется и не порождает запоздалый звонок.
    """
    from domains.platform.tasks.services import create_trial_no_show_task
    from domains.scheduling.schedule.models import LessonEnrollment

    lead_id = (
        LessonEnrollment.objects.for_tenant(organization)
        .filter(
            lesson=lesson,
            child=child,
            kind=LessonEnrollment.Kind.TRIAL,
            source_lead__isnull=False,
            cancelled_at__isnull=True,
        )
        .values_list("source_lead_id", flat=True)
        .first()
    )
    if lead_id is None:
        return False

    lead = Lead.objects.select_for_update().get(pk=lead_id, organization=organization)
    if lead.status != Lead.Status.TRIAL_SCHEDULED:
        return False

    create_trial_no_show_task(lead=lead, lesson=lesson, attendance=attendance)
    return True


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


def find_phone_matches(organization, phone) -> dict:
    """
    Кто уже есть с этим телефоном (TRU-97): заявки (кроме закрытых
    покупкой — это уже клиенты, они придут вторым списком) и родители в
    базе клиентов с их детьми. Показывается в форме ДО сохранения — иначе
    на одного ребёнка заведут три заявки. Неполный номер — пустой ответ.
    """
    try:
        normalized = normalize_phone_number(phone)
    except InvalidPhoneNumberError:
        return {"phone": None, "leads": [], "parents": []}
    leads = (
        Lead.objects.for_tenant(organization)
        .filter(phone=normalized, kind=LeadKind.NEW)
        .exclude(status=Lead.Status.PURCHASED)
        .order_by("-created_at")[:5]
    )
    parents = list(
        ParentContact.objects.for_tenant(organization)
        .filter(Q(phones__number=normalized) | Q(whatsapp=normalized))
        .distinct()[:5]
    )
    children = {}
    links = (
        ChildContact.objects.for_tenant(organization)
        .filter(parent_contact__in=parents, child__deleted_at__isnull=True)
        .select_related("child")
    )
    for link in links:
        children.setdefault(link.parent_contact_id, []).append(
            {"id": str(link.child_id), "full_name": link.child.full_name}
        )
    return {
        "phone": normalized,
        "leads": [
            {
                "id": str(lead.id),
                "parent_name": lead.parent_name,
                "child_name": lead.child_name,
                "status": lead.status,
                "status_label": lead.get_status_display(),
            }
            for lead in leads
        ],
        "parents": [
            {
                "id": str(parent.id),
                "full_name": parent.full_name,
                "children": children.get(parent.id, []),
            }
            for parent in parents
        ],
    }


class RenewalError(ValueError):
    """Продление не создать — сообщение для пользователя."""


@transaction.atomic
def create_renewal_lead(child, *, actor=None, assigned_to=None, comment="") -> tuple[Lead, bool]:
    """
    Заявка-продление по клиенту (TRU-98). Точки вызова — экран «Продления»
    (Bekzat, TRU-69) и автоправило «абонемент заканчивается» (TRU-108,
    actor=None — система).

    Идемпотентно: если по ребёнку уже есть открытое продление, возвращает
    его, а не заводит второе — автоправило может сработать каждый день.
    Возвращает (заявка, создана ли сейчас). Контакт — плательщик ребёнка
    (иначе первый контакт с телефоном).
    """
    organization = child.organization
    open_lead = (
        Lead.objects.for_tenant(organization)
        .filter(kind=LeadKind.RENEWAL, child=child)
        .exclude(status__in=[Lead.Status.PURCHASED, Lead.Status.REJECTED])
        .first()
    )
    if open_lead is not None:
        return open_lead, False
    links = (
        ChildContact.objects.for_tenant(organization)
        .filter(child=child, parent_contact__deleted_at__isnull=True)
        .select_related("parent_contact")
        .prefetch_related("parent_contact__phones")
        .order_by("-is_payer", "created_at")
    )
    contact, phone = None, None
    for link in links:
        parent = link.parent_contact
        numbers = [p.number for p in parent.phones.all()] + (
            [parent.whatsapp] if parent.whatsapp else []
        )
        if numbers:
            contact, phone = parent, numbers[0]
            break
    if contact is None:
        raise RenewalError("У ребёнка нет контакта с телефоном — добавьте его в карточке ребёнка.")
    branch = (
        child.group_memberships.filter(left_at__isnull=True, group__deleted_at__isnull=True)
        .values_list("group__branch", flat=True)
        .first()
    )
    lead = create_lead(
        organization=organization,
        actor=actor,
        kind=LeadKind.RENEWAL,
        child=child,
        parent_name=contact.full_name,
        phone=phone,
        child_name=child.full_name,
        child_age=getattr(child, "age", None),
        branch_id=branch,
        assigned_to=assigned_to or actor,
    )
    if comment:
        lead.comments.create(organization=organization, author=actor, text=comment)
    return lead, True


def close_renewal_on_sale(child, *, actor, subscription_name="") -> Lead | None:
    """
    Абонемент продан — открытое продление ребёнка закрывается «Купил»
    (TRU-98). Вызывается из продажи абонемента (деньги), чтобы заявка не
    висела на доске после оплаты и конверсия продлений считалась сама.
    Нет открытого продления — ничего не делает.
    """
    lead = (
        Lead.objects.for_tenant(child.organization)
        .filter(kind=LeadKind.RENEWAL, child=child)
        .exclude(status__in=[Lead.Status.PURCHASED, Lead.Status.REJECTED])
        .first()
    )
    if lead is None:
        return None
    comment = f"Продан абонемент «{subscription_name}»" if subscription_name else ""
    return change_status(lead, to_status=Lead.Status.PURCHASED, actor=actor, comment=comment)
