from rest_framework import serializers

from domains.platform.core.mixins import TenantCreateMixin

from .models import ScheduleTemplate, ScheduleTemplateSlot


class ScheduleTemplateSlotSerializer(TenantCreateMixin, serializers.ModelSerializer):
    weekday_display = serializers.CharField(source="get_weekday_display", read_only=True)

    class Meta:
        model = ScheduleTemplateSlot
        fields = [
            "id",
            "weekday",
            "weekday_display",
            "start_time",
            "duration_minutes",
            "room",
            "teacher",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class ScheduleTemplateSerializer(TenantCreateMixin, serializers.ModelSerializer):
    slots = ScheduleTemplateSlotSerializer(many=True, read_only=True)
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = ScheduleTemplate
        fields = [
            "id",
            "group",
            "valid_from",
            "valid_until",
            "generate_weeks_ahead",
            "note",
            "slots",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, attrs):
        if attrs.get("valid_until") and attrs.get("valid_from"):
            if attrs["valid_until"] <= attrs["valid_from"]:
                raise serializers.ValidationError(
                    {"valid_until": "Дата окончания должна быть позже даты начала."}
                )
        return attrs
