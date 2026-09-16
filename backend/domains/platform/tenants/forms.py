"""Django-формы для веб-экранов управления организацией/филиалами/залами
(серверный рендеринг, сессия — не DRF-сериализаторы из serializers.py,
те обслуживают JWT-API, см. ADR-002/docstring core/decorators.py)."""

import zoneinfo

from django import forms

from domains.platform.tenants.models import Branch, Room
from domains.platform.tenants.org_settings import (
    DEBT_OVERDUE_DAYS_THRESHOLD,
    GROUP_UNDERFILLED_PERCENT_THRESHOLD,
    SUBSCRIPTION_ENDING_DAYS_THRESHOLD,
    SUBSCRIPTION_ENDING_LESSONS_THRESHOLD,
)

# Полный zoneinfo.available_timezones() — это ~600 записей (включая
# исторические/редкие зоны), неюзабельно как <select>. Список — реальные
# IANA-зоны, а не текст "на глаз": страны СНГ/Азии, где вероятнее всего
# работают организации-клиенты, плюс UTC как явный нейтральный вариант.
TIMEZONE_CHOICES = [
    (tz, tz)
    for tz in [
        "Asia/Almaty",
        "Asia/Aqtobe",
        "Asia/Qyzylorda",
        "Asia/Bishkek",
        "Asia/Tashkent",
        "Asia/Dushanbe",
        "Asia/Ashgabat",
        "Asia/Yekaterinburg",
        "Asia/Novosibirsk",
        "Europe/Moscow",
        "UTC",
    ]
]


class KcFormMixin:
    """Проставляет .kc-form-input каждому текстовому/числовому/select-полю —
    иначе пришлось бы повторять attrs={"class": ...} на каждом поле формы."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput | forms.HiddenInput):
                continue
            existing = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing} kc-form-input".strip()


class OrganizationSettingsForm(KcFormMixin, forms.Form):
    # label — реальный русский текст (источник правды для ru, см.
    # static/site/js/i18n.js), а не ключ i18n: Django рендерит его сам,
    # шаблон добавляет data-i18n поверх при выводе (см. organization_settings.html).
    name = forms.CharField(max_length=255, label="Название организации")
    timezone = forms.ChoiceField(choices=TIMEZONE_CHOICES, label="Часовой пояс")
    subscription_ending_lessons_threshold = forms.IntegerField(
        min_value=0, max_value=100, label="Абонемент заканчивается при ≤ N занятий"
    )
    subscription_ending_days_threshold = forms.IntegerField(
        min_value=0, max_value=365, label="Абонемент заканчивается при ≤ N дней"
    )
    debt_overdue_days_threshold = forms.IntegerField(
        min_value=0, max_value=365, label="Задолженность просрочена после N дней"
    )
    group_underfilled_percent_threshold = forms.IntegerField(
        min_value=0, max_value=100, label="Группа недозаполнена при < X% вместимости"
    )

    def clean_timezone(self):
        tz_name = self.cleaned_data["timezone"]
        if tz_name not in zoneinfo.available_timezones():
            raise forms.ValidationError("Неизвестный часовой пояс.")
        return tz_name

    def save(self, organization):
        organization.name = self.cleaned_data["name"]
        organization.timezone = self.cleaned_data["timezone"]
        organization.settings = {
            **organization.settings,
            SUBSCRIPTION_ENDING_LESSONS_THRESHOLD: self.cleaned_data[
                SUBSCRIPTION_ENDING_LESSONS_THRESHOLD
            ],
            SUBSCRIPTION_ENDING_DAYS_THRESHOLD: self.cleaned_data[
                SUBSCRIPTION_ENDING_DAYS_THRESHOLD
            ],
            DEBT_OVERDUE_DAYS_THRESHOLD: self.cleaned_data[DEBT_OVERDUE_DAYS_THRESHOLD],
            GROUP_UNDERFILLED_PERCENT_THRESHOLD: self.cleaned_data[
                GROUP_UNDERFILLED_PERCENT_THRESHOLD
            ],
        }
        organization.save(update_fields=["name", "timezone", "settings", "updated_at"])
        return organization


# (код, русское название, ключ i18n) — код хранится в working_hours JSON,
# название рендерится в шаблоне с data-i18n=ключ поверх.
WEEKDAYS = [
    ("mon", "Понедельник", "org_settings.weekday_mon"),
    ("tue", "Вторник", "org_settings.weekday_tue"),
    ("wed", "Среда", "org_settings.weekday_wed"),
    ("thu", "Четверг", "org_settings.weekday_thu"),
    ("fri", "Пятница", "org_settings.weekday_fri"),
    ("sat", "Суббота", "org_settings.weekday_sat"),
    ("sun", "Воскресенье", "org_settings.weekday_sun"),
]


class BranchForm(KcFormMixin, forms.ModelForm):
    class Meta:
        model = Branch
        fields = ["name", "address", "phone"]
        labels = {
            "name": "Название филиала",
            "address": "Адрес",
            "phone": "Телефон",
        }
        # Django's Textarea по умолчанию rows=10 — огромное поле для
        # однострочного, по сути, адреса. 2 строки видно, дальше — скролл.
        widgets = {"address": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        working_hours = self.instance.working_hours or {}
        for code, _name, _key in WEEKDAYS:
            day = working_hours.get(code) or {}
            self.fields[f"{code}_closed"] = forms.BooleanField(
                required=False, initial=bool(day.get("closed", code in ("sat", "sun")))
            )
            self.fields[f"{code}_open"] = forms.TimeField(
                required=False,
                initial=day.get("open", "09:00"),
                widget=forms.TimeInput(attrs={"class": "kc-form-input"}),
            )
            self.fields[f"{code}_close"] = forms.TimeField(
                required=False,
                initial=day.get("close", "20:00"),
                widget=forms.TimeInput(attrs={"class": "kc-form-input"}),
            )

    def clean(self):
        cleaned = super().clean()
        working_hours = {}
        for code, _name, _key in WEEKDAYS:
            closed = cleaned.get(f"{code}_closed")
            if closed:
                working_hours[code] = {"closed": True}
            else:
                open_time = cleaned.get(f"{code}_open")
                close_time = cleaned.get(f"{code}_close")
                if open_time and close_time and close_time <= open_time:
                    self.add_error(f"{code}_close", "Время закрытия должно быть позже открытия.")
                working_hours[code] = {
                    "closed": False,
                    "open": open_time.strftime("%H:%M") if open_time else None,
                    "close": close_time.strftime("%H:%M") if close_time else None,
                }
        cleaned["working_hours"] = working_hours
        return cleaned

    def save(self, commit=True):
        self.instance.working_hours = self.cleaned_data["working_hours"]
        return super().save(commit=commit)


class RoomForm(KcFormMixin, forms.ModelForm):
    class Meta:
        model = Room
        fields = ["name", "capacity"]
        labels = {
            "name": "Название зала",
            "capacity": "Вместимость",
        }
