from django import forms

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
