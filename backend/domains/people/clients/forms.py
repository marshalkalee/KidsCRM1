"""
Форма веб-экрана "Контакты ребёнка" (серверный рендеринг, сессия) — не
DRF-сериализатор из serializers.py (тот обслуживает JWT-API), тот же
принцип разделения, что у tenants/forms.py.
"""

from django import forms
from django.utils import timezone

from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number
from domains.platform.tenants.forms import KcFormMixin
from domains.platform.tenants.models import Direction

from .models import Child, ChildContact, CommunicationLog, ContactPhone, ParentContact


class ChildContactForm(KcFormMixin, forms.ModelForm):
    class Meta:
        model = ChildContact
        fields = ["parent_contact", "role", "is_payer", "is_primary_contact"]
        labels = {
            "parent_contact": "Контакт",
            "role": "Роль",
            "is_payer": "Плательщик",
            "is_primary_contact": "Основной контакт",
        }

    def __init__(self, *args, child=None, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        # instance.pk у ChildContact непустой уже у нового объекта (UUID
        # генерируется в момент создания Python-инстанса, не при save()) —
        # "это редактирование" проверяем через _state.adding, а не по pk.
        self.is_edit = self.instance._state.adding is False
        self.child = child or self.instance.child
        org = organization or self.child.organization
        self.fields["parent_contact"].queryset = ParentContact.objects.for_tenant(org)
        if self.is_edit:
            # Кого именно привязали, на редактировании не меняем — для
            # этого отвязка и новая привязка, а не смена FK на лету.
            self.fields["parent_contact"].disabled = True

    def clean(self):
        cleaned = super().clean()
        parent_contact = cleaned.get("parent_contact")
        if parent_contact and self.child:
            qs = ChildContact.objects.filter(child=self.child, parent_contact=parent_contact)
            if self.is_edit:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error("parent_contact", "Этот контакт уже привязан к этому ребёнку.")
        return cleaned

    def save(self, commit=True):
        self.instance.child = self.child
        return super().save(commit=commit)


class ChildForm(KcFormMixin, forms.ModelForm):
    """Основные поля карточки ребёнка — редактирование из "быстрых действий"
    в шапке (ТЗ п. 4.1). Правило перехода статуса — то же самое, что в
    ChildSerializer (API), проверяется по единому Child.ALLOWED_STATUS_TRANSITIONS,
    а не переизобретается здесь."""

    class Meta:
        model = Child
        fields = [
            "full_name",
            "birth_date",
            "gender",
            "directions",
            "medical_notes",
            "photo_url",
            "status",
            "leave_reason",
            "consent_given",
        ]
        labels = {
            "full_name": "ФИО",
            "birth_date": "Дата рождения",
            "gender": "Пол",
            "directions": "Направления",
            "medical_notes": "Медицинские заметки и особенности",
            "photo_url": "Фото (URL)",
            "status": "Статус",
            "leave_reason": "Причина ухода",
            "consent_given": "Согласие на обработку данных получено",
        }
        widgets = {
            "medical_notes": forms.Textarea(attrs={"rows": 3}),
            "leave_reason": forms.Textarea(attrs={"rows": 2}),
            "directions": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        org = organization or self.instance.organization
        self.fields["directions"].queryset = Direction.objects.for_tenant(org).filter(
            is_active=True
        )

    def clean(self):
        cleaned = super().clean()
        birth_date = cleaned.get("birth_date")
        if birth_date and birth_date > timezone.now().date():
            self.add_error("birth_date", "Дата рождения не может быть в будущем.")

        new_status = cleaned.get("status")
        leave_reason = (cleaned.get("leave_reason") or "").strip()
        if new_status == Child.Status.LEFT and not leave_reason:
            self.add_error("leave_reason", "Причина ухода обязательна при переводе в «ушёл».")

        # self.instance ещё хранит значения ДО правки — construct_instance()
        # перезапишет их только в _post_clean(), после этого clean().
        if self.instance.pk and new_status and new_status != self.instance.status:
            allowed = Child.ALLOWED_STATUS_TRANSITIONS.get(self.instance.status, set())
            if new_status not in allowed:
                self.add_error(
                    "status",
                    f"Недопустимый переход статуса: {self.instance.status} → {new_status}.",
                )
        return cleaned


class CommunicationLogForm(KcFormMixin, forms.ModelForm):
    """Быстрое добавление записи в «Коммуникации» — минимум полей и кликов
    (ТЗ п. 4.1: критерий приёмки — иначе администратор не будет заполнять
    вкладку после звонка). parent_contact не обязателен — не любая запись
    привязана к конкретному контакту."""

    class Meta:
        model = CommunicationLog
        fields = ["channel", "parent_contact", "note"]
        labels = {
            "channel": "Канал",
            "parent_contact": "Контакт",
            "note": "Заметка",
        }
        widgets = {
            "channel": forms.RadioSelect,
            "note": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, child=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.child = child or self.instance.child
        self.fields["parent_contact"].queryset = ParentContact.objects.filter(
            child_links__child=self.child
        ).distinct()
        self.fields["parent_contact"].required = False

    def save(self, commit=True, author=None):
        self.instance.child = self.child
        if author is not None:
            self.instance.author = author
        return super().save(commit=commit)


class ParentContactForm(KcFormMixin, forms.ModelForm):
    class Meta:
        model = ParentContact
        fields = ["full_name", "whatsapp", "email"]
        labels = {
            "full_name": "ФИО",
            "whatsapp": "WhatsApp",
            "email": "Email",
        }

    def clean_whatsapp(self):
        value = self.cleaned_data.get("whatsapp")
        if not value:
            return value
        try:
            return normalize_phone_number(value)
        except InvalidPhoneNumberError as exc:
            raise forms.ValidationError(str(exc)) from exc


class ContactPhoneForm(KcFormMixin, forms.ModelForm):
    class Meta:
        model = ContactPhone
        fields = ["number", "phone_type"]
        labels = {
            "number": "Номер",
            "phone_type": "Тип",
        }

    def clean_number(self):
        value = self.cleaned_data.get("number")
        if not value:
            return value
        try:
            return normalize_phone_number(value)
        except InvalidPhoneNumberError as exc:
            raise forms.ValidationError(str(exc)) from exc

    @property
    def is_saved(self):
        # instance.pk у ContactPhone непустой уже у нового объекта (UUID
        # генерируется в момент создания Python-инстанса) — в шаблоне
        # нельзя прочитать _state.adding напрямую (имя с подчёркивания,
        # Django-шаблоны его молча не резолвят), поэтому оборачиваем здесь:
        # только сохранённая строка должна показывать чекбокс "Удалить".
        return self.instance._state.adding is False


# Несколько телефонов на форме родителя (ТЗ п. 3.1) — не отдельная форма на
# каждый номер, а формсет: одна строка = один ContactPhone, добавление
# строки — JS (static/site/js/components/formset.js), без похода на сервер.
# min_num=1/validate_min=True — "у родителя должен быть хотя бы один
# телефон", та же проверка, что у ParentContactSerializer.validate_phones в API.
# extra=0: Django считает видимые формы как max(initial, min_num) + extra —
# с extra=1 при создании (initial=0) показывало бы две пустые строки сразу
# (1 от min_num + 1 от extra), а не одну.
ContactPhoneFormSet = forms.inlineformset_factory(
    ParentContact,
    ContactPhone,
    form=ContactPhoneForm,
    extra=0,
    can_delete=True,
    min_num=1,
    validate_min=True,
)
