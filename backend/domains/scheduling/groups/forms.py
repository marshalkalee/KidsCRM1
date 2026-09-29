from django import forms

from domains.platform.core.text_validation import normalize_entity_name

from . import queries
from .models import Group


class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = [
            "name",
            "branch",
            "direction",
            "teachers",
            "capacity",
            "age_min",
            "age_max",
            "status",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "kc-form-input"}),
            "branch": forms.Select(attrs={"class": "kc-form-input"}),
            "direction": forms.Select(attrs={"class": "kc-form-input"}),
            "teachers": forms.SelectMultiple(attrs={"class": "kc-form-input"}),
            "capacity": forms.NumberInput(attrs={"class": "kc-form-input"}),
            "age_min": forms.NumberInput(attrs={"class": "kc-form-input"}),
            "age_max": forms.NumberInput(attrs={"class": "kc-form-input"}),
            "status": forms.Select(attrs={"class": "kc-form-input"}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization:
            # Архивные филиал/направление — только уже выбранные у этой
            # группы (TRU-77), общий код с API — queries.py.
            current = None if self.instance._state.adding else self.instance
            self.fields["branch"].queryset = queries.branch_choices(
                organization, current.branch if current else None
            )
            self.fields["direction"].queryset = queries.direction_choices(
                organization, current.direction if current else None
            )
            self.fields["teachers"].queryset = queries.teacher_choices(organization)

    def clean_name(self):
        return normalize_entity_name(self.cleaned_data["name"])

    def clean_capacity(self):
        value = self.cleaned_data["capacity"]
        if not 1 <= value <= 100:
            raise forms.ValidationError("Вместимость должна быть от 1 до 100.")
        return value

    def clean_age_min(self):
        value = self.cleaned_data.get("age_min")
        if value is not None and value > 99:
            raise forms.ValidationError("Возраст должен быть от 0 до 99 лет.")
        return value

    def clean_age_max(self):
        value = self.cleaned_data.get("age_max")
        if value is not None and value > 99:
            raise forms.ValidationError("Возраст должен быть от 0 до 99 лет.")
        return value
