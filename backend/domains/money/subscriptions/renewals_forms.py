"""Форма продажи продления — минимальная, только то, что нужно для
критерия «продаётся за минуту». Полноценного отдельного экрана продажи
в проекте пока нет вообще, эта форма его не заменяет."""

from django import forms

from domains.money.payments.models import Payment

from .subscription_types import get_selectable_subscription_types


class RenewalSaleForm(forms.Form):
    subscription_type = forms.ModelChoiceField(queryset=None, label="Тип абонемента")
    starts_on = forms.DateField(label="Дата начала")
    ends_on = forms.DateField(label="Дата окончания")
    discount_amount = forms.DecimalField(required=False, initial=0, label="Скидка")
    discount_reason = forms.CharField(required=False, label="Причина скидки")
    paid_amount = forms.DecimalField(label="Оплачено сейчас")
    payment_method = forms.ChoiceField(choices=Payment.Method.choices, label="Способ оплаты")

    def __init__(self, *args, organization=None, branch=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["subscription_type"].queryset = get_selectable_subscription_types(
            organization, branch=branch
        )
