"""
Карточка родителя — общая логика для старого веба (web_views.parent_card)
и API frontend2 (views.ParentContactViewSet, TRU-83).
"""

from decimal import Decimal

from domains.money.payments.models import Payment
from domains.money.subscriptions.debt import debt_by_child

from .models import ChildContact

# Сколько последних оплат показать в карточке родителя.
PARENT_PAYMENTS_LIMIT = 50

DELETE_BLOCKED_MESSAGE = "У родителя есть привязанные дети — сначала отвяжите их в карточках детей."


def parent_child_ids(organization, parent):
    return list(
        ChildContact.objects.for_tenant(organization)
        .filter(parent_contact=parent, child__deleted_at__isnull=True)
        .values_list("child_id", flat=True)
    )


def parent_money(organization, parent):
    """Сводно по всем детям родителя (ТЗ п. 4.1): суммарный долг — сервисом
    домена «Деньги» (debt_by_child — та же цифра, что в списке детей), и
    последние оплаты по абонементам всех его детей."""
    child_ids = parent_child_ids(organization, parent)
    total_debt = sum(debt_by_child(organization, child_ids).values(), Decimal(0))
    payments = (
        Payment.objects.for_tenant(organization)
        .filter(subscription__child_id__in=child_ids)
        .select_related("subscription__child", "subscription__subscription_type_version")
        .order_by("-paid_at")[:PARENT_PAYMENTS_LIMIT]
    )
    return {"total_debt": total_debt, "payments": list(payments)}


def can_delete_parent(organization, parent):
    """Удалять родителя можно, только когда к нему не привязан ни один
    ребёнок: иначе у ребёнка молча пропадает контакт и плательщик."""
    return not parent_child_ids(organization, parent)
