"""Parent-safe serializers for the parent portal."""

from django.utils import timezone
from rest_framework import serializers

from domains.scheduling.attendance.models import Attendance
from domains.scheduling.schedule.models import Lesson

from .models import ParentLessonRequest


class AttendancePeriodSerializer(serializers.Serializer):
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)

    def validate(self, attrs):
        date_from = attrs.get("date_from")
        date_to = attrs.get("date_to")
        if date_from and date_to and date_from > date_to:
            raise serializers.ValidationError(
                {"date_to": "Конец периода не может быть раньше начала."}
            )
        return attrs


class ParentLessonSerializer(serializers.ModelSerializer):
    """Upcoming lesson details safe to expose in the parent portal."""

    starts_at_local = serializers.SerializerMethodField()
    ends_at_local = serializers.SerializerMethodField()
    group_name = serializers.CharField(source="group.name", read_only=True, default=None)
    direction_name = serializers.CharField(
        source="group.direction.name", read_only=True, default=None
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    branch_name = serializers.SerializerMethodField()
    branch_address = serializers.SerializerMethodField()
    room_name = serializers.CharField(source="room.name", read_only=True, default=None)
    teacher_name = serializers.CharField(source="teacher.full_name", read_only=True, default=None)
    enrollment_kind = serializers.SerializerMethodField()
    cancel_reason_category_display = serializers.CharField(
        source="get_cancel_reason_category_display", read_only=True
    )
    rescheduled_to = serializers.SerializerMethodField()
    rescheduled_from_starts_at_local = serializers.SerializerMethodField()
    can_request_cancel = serializers.SerializerMethodField()

    class Meta:
        model = Lesson
        fields = [
            "id",
            "starts_at_local",
            "ends_at_local",
            "status",
            "status_display",
            "group_name",
            "direction_name",
            "branch_name",
            "branch_address",
            "room_name",
            "teacher_name",
            "enrollment_kind",
            "cancel_reason_category",
            "cancel_reason_category_display",
            "cancel_reason",
            "rescheduled_to",
            "rescheduled_from_starts_at_local",
            "can_request_cancel",
        ]

    def _local_datetime(self, value):
        organization = self.context["organization"]
        tz = timezone.zoneinfo.ZoneInfo(organization.timezone or "Asia/Almaty")
        return value.astimezone(tz).isoformat()

    def get_starts_at_local(self, obj):
        return self._local_datetime(obj.starts_at)

    def get_ends_at_local(self, obj):
        return self._local_datetime(obj.ends_at)

    def get_enrollment_kind(self, obj):
        enrollments = getattr(obj, "parent_enrollments", [])
        return enrollments[0].kind if enrollments else None

    def _branch(self, obj):
        if obj.group_id:
            return obj.group.branch
        return obj.room.branch if obj.room_id else None

    def get_branch_name(self, obj):
        branch = self._branch(obj)
        return branch.name if branch else None

    def get_branch_address(self, obj):
        branch = self._branch(obj)
        return branch.address if branch else ""

    def get_rescheduled_to(self, obj):
        try:
            lesson = obj.rescheduled_to
        except Lesson.DoesNotExist:
            return None
        return {
            "id": str(lesson.id),
            "starts_at_local": self._local_datetime(lesson.starts_at),
            "ends_at_local": self._local_datetime(lesson.ends_at),
        }

    def get_rescheduled_from_starts_at_local(self, obj):
        if not obj.rescheduled_from_id:
            return None
        return self._local_datetime(obj.rescheduled_from.starts_at)

    def get_can_request_cancel(self, obj):
        return obj.status == Lesson.Status.SCHEDULED and obj.starts_at > timezone.now()


class ParentMakeupCandidateSerializer(serializers.ModelSerializer):
    starts_at_local = serializers.SerializerMethodField()
    ends_at_local = serializers.SerializerMethodField()
    group_name = serializers.CharField(source="group.name", read_only=True)
    branch_name = serializers.CharField(source="group.branch.name", read_only=True)
    room_name = serializers.CharField(source="room.name", read_only=True, default=None)
    teacher_name = serializers.CharField(source="teacher.full_name", read_only=True, default=None)
    capacity = serializers.IntegerField(source="group.capacity", read_only=True)
    current_count = serializers.SerializerMethodField()
    spots_left = serializers.SerializerMethodField()

    class Meta:
        model = Lesson
        fields = [
            "id",
            "starts_at_local",
            "ends_at_local",
            "group_name",
            "branch_name",
            "room_name",
            "teacher_name",
            "capacity",
            "current_count",
            "spots_left",
        ]

    def _local_datetime(self, value):
        organization = self.context["organization"]
        tz = timezone.zoneinfo.ZoneInfo(organization.timezone or "Asia/Almaty")
        return value.astimezone(tz).isoformat()

    def get_starts_at_local(self, obj):
        return self._local_datetime(obj.starts_at)

    def get_ends_at_local(self, obj):
        return self._local_datetime(obj.ends_at)

    def get_current_count(self, obj):
        return obj.participants().count()

    def get_spots_left(self, obj):
        return max(obj.group.capacity - obj.participants().count(), 0)


class ParentMakeupBookingSerializer(serializers.Serializer):
    lesson_id = serializers.UUIDField()
    comment = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class ParentLessonRequestCreateSerializer(serializers.Serializer):
    lesson_id = serializers.UUIDField()
    type = serializers.ChoiceField(choices=ParentLessonRequest.Type.choices)
    comment = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    cancel_reason = serializers.ChoiceField(
        choices=ParentLessonRequest.CancelReason.choices, required=False, allow_blank=True
    )

    def validate(self, attrs):
        if attrs["type"] == ParentLessonRequest.Type.CANCEL and not attrs.get("cancel_reason"):
            raise serializers.ValidationError({"cancel_reason": "Укажите причину отмены занятия."})
        return attrs


class ParentLessonRequestSerializer(serializers.ModelSerializer):
    lesson = ParentMakeupCandidateSerializer(read_only=True)
    source_attendance_id = serializers.UUIDField(read_only=True, allow_null=True)
    processed_by_name = serializers.CharField(
        source="processed_by.full_name", read_only=True, default=None
    )
    cancel_reason_display = serializers.CharField(
        source="get_cancel_reason_display", read_only=True
    )

    class Meta:
        model = ParentLessonRequest
        fields = [
            "id",
            "type",
            "kind",
            "status",
            "comment",
            "cancel_reason",
            "cancel_reason_display",
            "notice_hours_required",
            "notice_is_timely",
            "will_be_charged",
            "lesson",
            "source_attendance_id",
            "spots_available_at_request",
            "processed_by_name",
            "processed_at",
            "rejection_reason",
            "created_at",
        ]


class ParentAttendanceSerializer(serializers.ModelSerializer):
    """Only the lesson facts a parent needs; no staff or subscription identifiers."""

    lesson_id = serializers.UUIDField(source="lesson.id", read_only=True)
    starts_at_local = serializers.SerializerMethodField()
    ends_at_local = serializers.SerializerMethodField()
    lesson_name = serializers.SerializerMethodField()
    group_name = serializers.CharField(source="lesson.group.name", read_only=True, default=None)
    branch_name = serializers.CharField(
        source="lesson.group.branch.name", read_only=True, default=None
    )
    room_name = serializers.CharField(source="lesson.room.name", read_only=True, default=None)

    class Meta:
        model = Attendance
        fields = [
            "id",
            "lesson_id",
            "starts_at_local",
            "ends_at_local",
            "lesson_name",
            "group_name",
            "branch_name",
            "room_name",
            "status",
            "absence_reason",
            "consumed_from_subscription",
            "consume_outcome",
        ]

    def _local_datetime(self, value):
        organization = self.context["organization"]
        tz = timezone.zoneinfo.ZoneInfo(organization.timezone or "Asia/Almaty")
        return value.astimezone(tz).isoformat()

    def get_starts_at_local(self, obj):
        return self._local_datetime(obj.lesson.starts_at)

    def get_ends_at_local(self, obj):
        return self._local_datetime(obj.lesson.ends_at)

    def get_lesson_name(self, obj):
        if obj.lesson.group_id:
            return obj.lesson.group.direction.name
        return None


class ParentAvailableMakeupSerializer(serializers.Serializer):
    attendance_id = serializers.UUIDField(source="attendance.id")
    starts_at_local = serializers.SerializerMethodField()
    lesson_name = serializers.SerializerMethodField()
    group_name = serializers.CharField(source="attendance.lesson.group.name", default=None)
    absence_reason = serializers.CharField(source="attendance.absence_reason")
    expires_on = serializers.DateField()
    days_left = serializers.IntegerField()

    def _lesson(self, obj):
        return obj["attendance"].lesson

    def get_starts_at_local(self, obj):
        organization = self.context["organization"]
        tz = timezone.zoneinfo.ZoneInfo(organization.timezone or "Asia/Almaty")
        return self._lesson(obj).starts_at.astimezone(tz).isoformat()

    def get_lesson_name(self, obj):
        lesson = self._lesson(obj)
        if lesson.group_id:
            return lesson.group.direction.name
        return None
