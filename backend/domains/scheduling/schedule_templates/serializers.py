from rest_framework import serializers

from domains.platform.core.mixins import TenantCreateMixin

from .models import ScheduleTemplate, ScheduleTemplateSlot


class ScheduleTemplateSlotSerializer(TenantCreateMixin, serializers.ModelSerializer):
    weekday_display = serializers.CharField(source="get_weekday_display", read_only=True)
    # Те же границы, что у фиксированного расписания группы (groups).
    duration_minutes = serializers.IntegerField(min_value=15, max_value=360, required=False)

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
        valid_from = attrs.get("valid_from", getattr(self.instance, "valid_from", None))
        valid_until = attrs.get("valid_until", getattr(self.instance, "valid_until", None))
        if valid_from and valid_until and valid_until <= valid_from:
            raise serializers.ValidationError(
                {"valid_until": "Дата окончания должна быть позже даты начала."}
            )
        return attrs
