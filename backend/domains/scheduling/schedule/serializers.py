from django.utils import timezone
from rest_framework import serializers

from domains.platform.core.mixins import TenantCreateMixin

from .models import Lesson


class LessonSerializer(TenantCreateMixin, serializers.ModelSerializer):
    starts_at_local = serializers.SerializerMethodField()
    ends_at_local = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    rescheduled_to_id = serializers.SerializerMethodField()

    class Meta:
        model = Lesson
        fields = [
            "id",
            "group",
            "schedule_slot",
            "room",
            "teacher",
            "starts_at",
            "ends_at",
            "starts_at_local",
            "ends_at_local",
            "status",
            "status_display",
            "rescheduled_from",
            "rescheduled_to_id",
            "is_modified",
            "cancel_reason",
            "note",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_starts_at_local(self, obj):
        org = self.context["request"].organization
        tz = timezone.zoneinfo.ZoneInfo(org.timezone or "Asia/Almaty")
        return obj.starts_at.astimezone(tz).isoformat()

    def get_ends_at_local(self, obj):
        org = self.context["request"].organization
        tz = timezone.zoneinfo.ZoneInfo(org.timezone or "Asia/Almaty")
        return obj.ends_at.astimezone(tz).isoformat()

    def get_rescheduled_to_id(self, obj):
        try:
            return str(obj.rescheduled_to.id)
        except Lesson.DoesNotExist:
            return None

    def validate(self, attrs):
        if attrs.get("ends_at") and attrs.get("starts_at"):
            if attrs["ends_at"] <= attrs["starts_at"]:
                raise serializers.ValidationError(
                    {"ends_at": "Конец занятия должен быть позже начала."}
                )
        return attrs
