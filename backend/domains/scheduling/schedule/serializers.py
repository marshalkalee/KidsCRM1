from django.utils import timezone
from rest_framework import serializers

from domains.platform.core.mixins import TenantCreateMixin

from .models import Lesson


class LessonSerializer(TenantCreateMixin, serializers.ModelSerializer):
    starts_at_local = serializers.SerializerMethodField()
    ends_at_local = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    rescheduled_to_id = serializers.SerializerMethodField()

    # Поля для календаря — считаются из уже загруженных select_related/
    # prefetch_related объектов во view, доп. запросов не делают (см.
    # LessonViewSet.get_queryset).
    group_name = serializers.SerializerMethodField()
    direction_id = serializers.SerializerMethodField()
    direction_color = serializers.SerializerMethodField()
    room_name = serializers.SerializerMethodField()
    teacher_name = serializers.SerializerMethodField()
    capacity = serializers.SerializerMethodField()
    enrolled_count = serializers.SerializerMethodField()

    class Meta:
        model = Lesson
        fields = [
            "id",
            "group",
            "group_name",
            "direction_id",
            "direction_color",
            "schedule_slot",
            "room",
            "room_name",
            "teacher",
            "teacher_name",
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
            "capacity",
            "enrolled_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_group_name(self, obj):
        return obj.group.name if obj.group else None

    def get_direction_id(self, obj):
        return obj.group.direction_id if obj.group else None

    def get_direction_color(self, obj):
        return obj.group.direction.color if obj.group else None

    def get_room_name(self, obj):
        return obj.room.name if obj.room else None

    def get_teacher_name(self, obj):
        return obj.teacher.full_name if obj.teacher else None

    def get_capacity(self, obj):
        return obj.group.capacity if obj.group else None

    def get_enrolled_count(self, obj):
        return obj.group.enrolled_count if obj.group else None

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
