"""Публичный приём заявок с сайта (ТЗ п. 5.1, TRU-110). Отдельный,
МИНИМАЛЬНЫЙ сериализатор — не переиспользуем LeadSerializer: тот отдаёт
много внутренних полей на чтение, здесь только запись шести полей с
сайта плюс honeypot."""

from rest_framework import serializers

from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number


class PublicLeadSerializer(serializers.Serializer):
    parent_name = serializers.CharField(max_length=255, trim_whitespace=True)
    phone = serializers.CharField(max_length=32)
    child_name = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    child_age = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=25, default=None
    )
    direction_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    branch_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    comment = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")
    # Публикация (TRU-165): код K12 явно или метка из ссылки на сайт.
    campaign = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    utm_content = serializers.CharField(
        max_length=100, required=False, allow_blank=True, default=""
    )
    # Honeypot — скрытое на сайте поле. Человек его не видит и не заполняет;
    # простые боты, заполняющие форму подряд, часто заполняют любое найденное
    # поле. Непустое значение здесь не считается ошибкой ввода (бот не должен
    # понять, что его поймали) — проверяется отдельно во view.
    website = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")

    def validate_parent_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Укажите имя.")
        return value

    def validate_phone(self, value):
        try:
            return normalize_phone_number(value)
        except InvalidPhoneNumberError as exc:
            raise serializers.ValidationError(str(exc)) from exc
