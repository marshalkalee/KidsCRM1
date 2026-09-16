"""
Форма веб-экрана "Контакты ребёнка" (серверный рендеринг, сессия) — не
DRF-сериализатор из serializers.py (тот обслуживает JWT-API), тот же
принцип разделения, что у tenants/forms.py.
"""

from django import forms

from domains.platform.tenants.forms import KcFormMixin

from .models import ChildContact, ParentContact


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
