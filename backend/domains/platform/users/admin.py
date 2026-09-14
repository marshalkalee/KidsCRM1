from django import forms
from django.contrib import admin
from django.contrib.auth.forms import ReadOnlyPasswordHashField

from .models import User


class UserCreationForm(forms.ModelForm):
    password1 = forms.CharField(label="Пароль", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Пароль (повторно)", widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ["phone", "full_name", "organization", "role"]

    def clean_password2(self):
        p1, p2 = self.cleaned_data.get("password1"), self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Пароли не совпадают")
        return p2

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class UserChangeForm(forms.ModelForm):
    password = ReadOnlyPasswordHashField(
        label="Пароль",
        help_text="Пароль меняется отдельной формой смены пароля, не здесь.",
    )

    class Meta:
        model = User
        fields = ["phone", "full_name", "organization", "branches", "role", "is_active", "is_staff"]


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    add_form = UserCreationForm
    form = UserChangeForm
    add_fieldsets = (
        (
            None,
            {"fields": ("phone", "full_name", "password1", "password2", "organization", "role")},
        ),
    )
    fieldsets = (
        (None, {"fields": ("phone", "full_name", "password")}),
        ("KidsCRM", {"fields": ("organization", "branches", "role")}),
        ("Права", {"fields": ("is_active", "is_staff", "is_superuser")}),
    )
    list_display = ["full_name", "phone", "organization", "role", "is_staff"]
    list_filter = ["organization", "role", "is_staff"]
    search_fields = ["full_name", "phone"]
    filter_horizontal = ["branches"]
    ordering = ["full_name"]

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs["form"] = self.add_form
            kwargs["fields"] = None
        return super().get_form(request, obj, **kwargs)
