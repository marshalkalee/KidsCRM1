"""
Экран быстрой оплаты (ТЗ п. 4.4, 10.4 — ≤1 минута). Вкладка "Оплаты"
карточки ребёнка — подключается через контракт CHILD_CARD_TABS
(domains.people.clients.child_card_tabs), фрагмент без обвязки страницы.

"Оплата без абонемента" не поддержана в этой версии осознанно, не
случайно — требует явного решения команды, не решено втихую.
"""

import uuid

from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, render

from domains.money.subscriptions.models import Subscription
from domains.people.clients.models import Child

from .debt import debt_for_child
from .models import Payment
from .services import record_payment


def child_payments_tab(request, child_id):
    child = get_object_or_404(Child.objects.for_tenant(request.user.organization), pk=child_id)
    subscription = (
        Subscription.objects.for_tenant(child.organization)
        .filter(child=child, status__in=[Subscription.Status.ACTIVE, Subscription.Status.FROZEN])
        .order_by("ends_on")
        .first()
    )
    context = {
        "child": child,
        "subscription": subscription,
        "debt": debt_for_child(child) if subscription else 0,
        "methods": Payment.Method.choices,
        "idempotency_key": uuid.uuid4(),
    }
    return render(request, "payments/_child_payments_tab.html", context)


def record_payment_view(request, child_id):
    if request.method != "POST":
        return HttpResponseBadRequest()

    child = get_object_or_404(Child.objects.for_tenant(request.user.organization), pk=child_id)
    subscription = get_object_or_404(
        Subscription.objects.for_tenant(child.organization),
        pk=request.POST.get("subscription_id"),
        child=child,
    )
    amount = request.POST.get("amount")
    method = request.POST.get("method")
    idempotency_key = request.POST.get("idempotency_key")
    if not amount or not method or not idempotency_key:
        return JsonResponse({"error": "Не хватает обязательных полей"}, status=400)

    payment = record_payment(
        actor=request.user,
        subscription=subscription,
        amount=amount,
        method=method,
        comment=request.POST.get("comment", ""),
        idempotency_key=idempotency_key,
    )
    return JsonResponse(
        {
            "paid_amount": str(payment.amount),
            "remaining_debt": str(debt_for_child(child)),
        }
    )
