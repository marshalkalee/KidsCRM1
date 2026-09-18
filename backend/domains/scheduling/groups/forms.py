from django import forms

from domains.platform.tenants.models import Branch, Direction
from domains.platform.users.models import User

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
            self.fields["branch"].queryset = Branch.objects.for_tenant(organization).filter(
                is_active=True
            )
            self.fields["direction"].queryset = Direction.objects.for_tenant(organization).filter(
                is_active=True
            )
            self.fields["teachers"].queryset = User.objects.filter(
                organization=organization, role="teacher"
            )
