"""Django-формы для веб-экранов управления организацией/филиалами/залами
(серверный рендеринг, сессия — не DRF-сериализаторы из serializers.py,
те обслуживают JWT-API, см. ADR-002/docstring core/decorators.py)."""

import zoneinfo

from django import forms

from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number
from domains.platform.core.text_validation import normalize_entity_name
from domains.platform.tenants.models import Branch, Direction, Room
from domains.platform.tenants.org_settings import (
    DEBT_OVERDUE_DAYS_THRESHOLD,
    DEFAULT_ORG_SETTINGS,
    DIGEST_HOUR,
    DIGEST_WEEKDAY,
    GROUP_UNDERFILLED_PERCENT_THRESHOLD,
    LEAD_STALE_DAYS_THRESHOLD,
    PARENT_CANCEL_CHARGE_ON_TIME,
    PARENT_CANCEL_NOTICE_HOURS,
    RENEWAL_GRACE_DAYS,
    RISK_ABSENCE_CHANGE_PP_THRESHOLD,
    RISK_CURRENT_ABSENCES_MIN,
    RULE_DEBT_REMINDER_ENABLED,
    RULE_LEAD_STALE_ENABLED,
    RULE_MISSING_SUBSCRIPTION_ENABLED,
    RULE_RENEWAL_OFFER_ENABLED,
    RULE_TRIAL_NO_SHOW_ENABLED,
    SUBSCRIPTION_ENDING_DAYS_THRESHOLD,
    SUBSCRIPTION_ENDING_LESSONS_THRESHOLD,
    get_org_setting,
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
    иначе пришлось бы повторять attrs={"class": ...} на каждом поле формы.

    CheckboxSelectMultiple/RadioSelect — тоже не текстовые поля, хоть и не
    CheckboxInput: без этого исключения .kc-form-input (display:block;
    width:100%) попадал бы на каждый чекбокс/радио в списке (например,
    "Доступно в филиалах" у направления, "Канал" в форме коммуникации),
    раздувая его на всю строку и роняя подпись под него."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(
                field.widget,
                forms.CheckboxInput
                | forms.CheckboxSelectMultiple
                | forms.HiddenInput
                | forms.RadioSelect,
            ):
                continue
            existing = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing} kc-form-input".strip()


class OrganizationSettingsForm(KcFormMixin, forms.Form):
    # label — реальный русский текст (источник правды для ru, см.
    # static/site/js/i18n.js), а не ключ i18n: Django рендерит его сам,
    # шаблон добавляет data-i18n поверх при выводе (см. organization_settings.html).
    name = forms.CharField(max_length=255, label="Название организации")
    timezone = forms.ChoiceField(choices=TIMEZONE_CHOICES, label="Часовой пояс")
    website_domain = forms.CharField(
        max_length=255,
        required=False,
        label="Домен сайта (для формы заявок)",
        help_text=(
            "Например https://trueballet.kz — форма на сайте сможет слать "
            "заявки только с этого адреса"
        ),
    )
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
    risk_absence_change_pp_threshold = forms.IntegerField(
        min_value=1,
        max_value=100,
        required=False,
        label="Рост пропусков относительно личной нормы, п.п.",
    )
    risk_current_absences_min = forms.IntegerField(
        min_value=1,
        max_value=100,
        required=False,
        label="Минимум пропусков за период для риск-сигнала",
    )
    lead_stale_days_threshold = forms.IntegerField(
        min_value=0, max_value=90, required=False, label="Заявка без движения после N дней"
    )
    renewal_grace_days = forms.IntegerField(
        min_value=0,
        max_value=120,
        required=False,
        label="Продление: новый абонемент не позже N дней после окончания",
    )
    rule_lead_stale_enabled = forms.BooleanField(
        required=False, label="Напоминать перезвонить по зависшим заявкам"
    )
    rule_renewal_offer_enabled = forms.BooleanField(
        required=False, label="Предлагать продление заранее"
    )
    rule_debt_reminder_enabled = forms.BooleanField(
        required=False, label="Напоминать о просроченном долге"
    )
    rule_missing_subscription_enabled = forms.BooleanField(
        required=False, label="Напоминать оформить абонемент без него"
    )
    rule_trial_no_show_enabled = forms.BooleanField(
        required=False, label="Напоминать перезвонить после пропуска пробного"
    )
    parent_cancel_notice_hours = forms.IntegerField(
        min_value=0,
        max_value=168,
        required=False,
        label="Срок предупреждения об отмене, часов",
    )
    parent_cancel_charge_on_time = forms.BooleanField(
        required=False,
        label="Списывать занятие при своевременном предупреждении",
    )
    digest_weekday = forms.IntegerField(
        min_value=0, max_value=6, required=False, label="День дайджеста ИИ (0 — понедельник)"
    )
    digest_hour = forms.IntegerField(
        min_value=0, max_value=23, required=False, label="Час дайджеста ИИ"
    )

    def clean_timezone(self):
        tz_name = self.cleaned_data["timezone"]
        if tz_name not in zoneinfo.available_timezones():
            raise forms.ValidationError("Неизвестный часовой пояс.")
        return tz_name

    def clean_name(self):
        return normalize_entity_name(self.cleaned_data["name"])

    @classmethod
    def for_organization(cls, organization):
        """Форма с текущими значениями организации (пороги — с фолбэком на
        значения по умолчанию) — общая для экрана настроек и мастера онбординга."""
        return cls(
            initial={
                "name": organization.name,
                "timezone": organization.timezone,
                "website_domain": organization.website_domain,
                **{
                    key: organization.settings.get(key, default)
                    for key, default in DEFAULT_ORG_SETTINGS.items()
                },
            }
        )

    def save(self, organization):
        organization.name = self.cleaned_data["name"]
        organization.timezone = self.cleaned_data["timezone"]
        organization.website_domain = self.cleaned_data["website_domain"]
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
            RISK_ABSENCE_CHANGE_PP_THRESHOLD: self.cleaned_data.get(
                RISK_ABSENCE_CHANGE_PP_THRESHOLD
            )
            or get_org_setting(organization, RISK_ABSENCE_CHANGE_PP_THRESHOLD),
            RISK_CURRENT_ABSENCES_MIN: self.cleaned_data.get(RISK_CURRENT_ABSENCES_MIN)
            or get_org_setting(organization, RISK_CURRENT_ABSENCES_MIN),
            LEAD_STALE_DAYS_THRESHOLD: self.cleaned_data[LEAD_STALE_DAYS_THRESHOLD]
            if self.cleaned_data[LEAD_STALE_DAYS_THRESHOLD] is not None
            else organization.settings.get(
                LEAD_STALE_DAYS_THRESHOLD, DEFAULT_ORG_SETTINGS[LEAD_STALE_DAYS_THRESHOLD]
            ),
            RENEWAL_GRACE_DAYS: (
                self.cleaned_data.get(RENEWAL_GRACE_DAYS)
                if self.cleaned_data.get(RENEWAL_GRACE_DAYS) is not None
                else get_org_setting(organization, RENEWAL_GRACE_DAYS)
            ),
            RULE_LEAD_STALE_ENABLED: self.cleaned_data[RULE_LEAD_STALE_ENABLED],
            RULE_RENEWAL_OFFER_ENABLED: self.cleaned_data[RULE_RENEWAL_OFFER_ENABLED],
            RULE_DEBT_REMINDER_ENABLED: self.cleaned_data[RULE_DEBT_REMINDER_ENABLED],
            RULE_MISSING_SUBSCRIPTION_ENABLED: self.cleaned_data[RULE_MISSING_SUBSCRIPTION_ENABLED],
            RULE_TRIAL_NO_SHOW_ENABLED: self.cleaned_data[RULE_TRIAL_NO_SHOW_ENABLED],
            PARENT_CANCEL_NOTICE_HOURS: (
                self.cleaned_data.get(PARENT_CANCEL_NOTICE_HOURS)
                if self.cleaned_data.get(PARENT_CANCEL_NOTICE_HOURS) is not None
                else get_org_setting(organization, PARENT_CANCEL_NOTICE_HOURS)
            ),
            PARENT_CANCEL_CHARGE_ON_TIME: (
                self.cleaned_data[PARENT_CANCEL_CHARGE_ON_TIME]
                if PARENT_CANCEL_CHARGE_ON_TIME in self.data
                else get_org_setting(organization, PARENT_CANCEL_CHARGE_ON_TIME)
            ),
            **{
                key: self.cleaned_data[key]
                if self.cleaned_data.get(key) is not None
                else get_org_setting(organization, key)
                for key in (DIGEST_WEEKDAY, DIGEST_HOUR)
            },
        }
        organization.save(
            update_fields=["name", "timezone", "settings", "website_domain", "updated_at"]
        )
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

    def clean_name(self):
        return normalize_entity_name(self.cleaned_data["name"])

    def clean_phone(self):
        value = self.cleaned_data.get("phone")
        if not value:
            return value
        try:
            return normalize_phone_number(value)
        except InvalidPhoneNumberError as exc:
            raise forms.ValidationError(str(exc)) from exc

    def clean_address(self):
        value = self.cleaned_data.get("address", "").strip()
        if len(value) > 500:
            raise forms.ValidationError("Введите не более 500 символов.")
        return value

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

    def clean_name(self):
        return normalize_entity_name(self.cleaned_data["name"], max_length=100)

    def clean_capacity(self):
        value = self.cleaned_data.get("capacity")
        if value is not None and not 1 <= value <= 1000:
            raise forms.ValidationError("Вместимость должна быть от 1 до 1000.")
        return value


class BranchMultipleChoiceField(forms.ModelMultipleChoiceField):
    """Branch.__str__() включает organization_id (для админки/дебага) —
    в чекбоксах формы это выглядело бы как "Филиал (uuid-...)", показываем
    только название."""

    def label_from_instance(self, obj):
        return obj.name


class DirectionForm(KcFormMixin, forms.ModelForm):
    branches = BranchMultipleChoiceField(
        queryset=Branch.objects.none(),
        required=False,
        widget=forms.SelectMultiple,
        label="Доступно в филиалах",
    )

    class Meta:
        model = Direction
        fields = ["name", "color", "age_min", "age_max", "branches"]
        labels = {
            "name": "Название направления",
            "color": "Цвет для календаря",
            "age_min": "Возраст от",
            "age_max": "Возраст до",
        }
        widgets = {
            "color": forms.TextInput(attrs={"type": "color"}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        org = organization or self.instance.organization
        self.fields["branches"].queryset = Branch.objects.for_tenant(org).filter(is_active=True)

    def clean_name(self):
        return normalize_entity_name(self.cleaned_data["name"])

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

    def clean(self):
        cleaned = super().clean()
        age_min = cleaned.get("age_min")
        age_max = cleaned.get("age_max")
        if age_min is not None and age_max is not None and age_max < age_min:
            self.add_error("age_max", "Возраст «до» не может быть меньше возраста «от».")
        return cleaned
