from django.utils import timezone
from rest_framework import serializers

from domains.people.clients.models import Child
from domains.scheduling.schedule.models import Lesson

from .models import Attendance


class AttendanceSerializer(serializers.ModelSerializer):
    child_name = serializers.CharField(source="child.full_name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    absence_reason_display = serializers.CharField(
        source="get_absence_reason_display", read_only=True
    )
    marked_by_name = serializers.CharField(
        source="marked_by.full_name", read_only=True, default=None
    )

    class Meta:
        model = Attendance
        fields = [
            "id",
            "lesson",
            "child",
            "child_name",
            "status",
            "status_display",
            "absence_reason",
            "absence_reason_display",
            "consumed_from_subscription",
            "subscription_id",
            "consume_outcome",
            "no_subscription_flag",
            "is_retroactive_edit",
            "marked_by",
            "marked_by_name",
            "marked_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "consumed_from_subscription",
            "subscription_id",
            "consume_outcome",
            "no_subscription_flag",
            "is_retroactive_edit",
            "marked_by",
            "marked_at",
            "created_at",
            "updated_at",
        ]


class AttendanceHistoryQuerySerializer(serializers.Serializer):
    child = serializers.PrimaryKeyRelatedField(queryset=Child.objects.none())
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            self.fields["child"].queryset = Child.objects.for_tenant(request.organization)

    def validate(self, attrs):
        if attrs.get("date_from") and attrs.get("date_to"):
            if attrs["date_from"] > attrs["date_to"]:
                raise serializers.ValidationError(
                    {"date_to": "Конец периода не может быть раньше начала."}
                )
        return attrs


class AttendanceHistorySerializer(serializers.ModelSerializer):
    """Строка истории для карточки ребёнка и будущей аналитики пропусков."""

    starts_at_local = serializers.SerializerMethodField()
    ends_at_local = serializers.SerializerMethodField()
    lesson_name = serializers.SerializerMethodField()
    group_id = serializers.UUIDField(source="lesson.group_id", read_only=True, allow_null=True)
    group_name = serializers.CharField(source="lesson.group.name", read_only=True, default=None)
    branch_name = serializers.CharField(
        source="lesson.group.branch.name", read_only=True, default=None
    )
    direction_name = serializers.CharField(
        source="lesson.group.direction.name", read_only=True, default=None
    )
    room_name = serializers.CharField(source="lesson.room.name", read_only=True, default=None)
    teacher_name = serializers.CharField(
        source="lesson.teacher.full_name", read_only=True, default=None
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    absence_reason_display = serializers.CharField(
        source="get_absence_reason_display", read_only=True
    )
    consumption_display = serializers.SerializerMethodField()
    marked_by_name = serializers.CharField(
        source="marked_by.full_name", read_only=True, default=None
    )

    class Meta:
        model = Attendance
        fields = [
            "id",
            "lesson",
            "starts_at_local",
            "ends_at_local",
            "lesson_name",
            "group_id",
            "group_name",
            "branch_name",
            "direction_name",
            "room_name",
            "teacher_name",
            "status",
            "status_display",
            "absence_reason",
            "absence_reason_display",
            "consumed_from_subscription",
            "subscription_id",
            "consume_outcome",
            "consumption_display",
            "no_subscription_flag",
            "is_retroactive_edit",
            "marked_by_name",
            "marked_at",
        ]

    def _local_datetime(self, value):
        organization = self.context["request"].organization
        tz = timezone.zoneinfo.ZoneInfo(organization.timezone or "Asia/Almaty")
        return value.astimezone(tz).isoformat()

    def get_starts_at_local(self, obj):
        return self._local_datetime(obj.lesson.starts_at)

    def get_ends_at_local(self, obj):
        return self._local_datetime(obj.lesson.ends_at)

    def get_lesson_name(self, obj):
        if obj.lesson.group_id:
            return obj.lesson.group.direction.name
        return "Индивидуальное занятие"

    def get_consumption_display(self, obj):
        if obj.consumed_from_subscription:
            return "Списано с абонемента"
        labels = {
            "no_active_subscription": "Не списано: нет активного абонемента",
            "subscription_exhausted": "Не списано: занятия закончились",
            "subscription_frozen": "Не списано: абонемент заморожен",
            "rule_forbids": "Не списано: правило абонемента запрещает списание",
            "makeup_no_charge": "Не списано: отработка без нового списания",
            "trial_no_charge": "Не списано: пробное занятие",
        }
        return labels.get(obj.consume_outcome, "Не списано")


class AttendanceMarkSerializer(serializers.Serializer):
    """Единственный вход для смены статуса (см. Attendance.mark) — создаёт
    запись посещаемости при первой отметке (get_or_create по паре
    lesson+child в view) и вызывает SubscriptionService на каждую отметку,
    в т.ч. повторную (идемпотентно — см. Attendance._consume/_revert)."""

    lesson = serializers.PrimaryKeyRelatedField(queryset=Lesson.objects.none())
    child = serializers.PrimaryKeyRelatedField(queryset=Child.objects.none())
    status = serializers.ChoiceField(choices=Attendance.Status.choices)
    absence_reason = serializers.ChoiceField(
        choices=Attendance.AbsenceReason.choices, required=False, allow_blank=True, default=""
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            org = request.organization
            self.fields["lesson"].queryset = Lesson.objects.for_tenant(org)
            self.fields["child"].queryset = Child.objects.for_tenant(org)

    def validate(self, attrs):
        lesson = attrs["lesson"]
        child = attrs["child"]
        if not lesson.participants().filter(pk=child.pk).exists():
            raise serializers.ValidationError({"child": "Ребёнок не записан на это занятие."})
        if attrs["status"] == Attendance.Status.ABSENT and not attrs.get("absence_reason"):
            attrs["absence_reason"] = Attendance.AbsenceReason.NO_REASON
        return attrs


class AttendanceRosterEntrySerializer(serializers.Serializer):
    """TRU-56: строка ростера занятия — {"child": Child, "attendance":
    Attendance | None, "enrollment_kind": "makeup"|"trial"|None} (см.
    AttendanceViewSet.roster). Ребёнок без Attendance ещё не отмечен — это
    НЕ то же самое, что status="absent". enrollment_kind — пометка типа
    для записанных «поверх» группы (TRU-53); None — обычный участник."""

    child = serializers.UUIDField(source="child.id")
    child_name = serializers.CharField(source="child.full_name")
    child_birth_date = serializers.DateField(source="child.birth_date")
    child_age = serializers.IntegerField(source="child.age")
    child_gender = serializers.CharField(source="child.gender")
    child_photo_url = serializers.URLField(source="child.photo_url", allow_blank=True)
    child_status = serializers.CharField(source="child.status")
    attendance_id = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    status_display = serializers.SerializerMethodField()
    absence_reason = serializers.SerializerMethodField()
    consumed_from_subscription = serializers.SerializerMethodField()
    no_subscription_flag = serializers.SerializerMethodField()
    is_retroactive_edit = serializers.SerializerMethodField()
    marked_at = serializers.SerializerMethodField()
    enrollment_kind = serializers.SerializerMethodField()
    source_lead_id = serializers.SerializerMethodField()
    parent_cancel_notice = serializers.SerializerMethodField()

    def get_enrollment_kind(self, obj):
        return obj.get("enrollment_kind")

    def get_source_lead_id(self, obj):
        source_lead_id = obj.get("source_lead_id")
        return str(source_lead_id) if source_lead_id else None

    def get_parent_cancel_notice(self, obj):
        request = obj.get("parent_cancel_notice")
        if request is None:
            return None
        return {
            "request_id": str(request.id),
            "reason": request.cancel_reason,
            "reason_display": request.get_cancel_reason_display(),
            "comment": request.comment,
            "notice_is_timely": request.notice_is_timely,
            "will_be_charged": request.will_be_charged,
            "created_at": request.created_at,
        }

    def get_attendance_id(self, obj):
        attendance = obj["attendance"]
        return attendance.id if attendance else None

    def get_status(self, obj):
        attendance = obj["attendance"]
        return attendance.status if attendance else None

    def get_status_display(self, obj):
        attendance = obj["attendance"]
        return attendance.get_status_display() if attendance else None

    def get_absence_reason(self, obj):
        attendance = obj["attendance"]
        return attendance.absence_reason if attendance else ""

    def get_consumed_from_subscription(self, obj):
        attendance = obj["attendance"]
        return bool(attendance and attendance.consumed_from_subscription)

    def get_no_subscription_flag(self, obj):
        attendance = obj["attendance"]
        return bool(attendance and attendance.no_subscription_flag)

    def get_is_retroactive_edit(self, obj):
        attendance = obj["attendance"]
        return bool(attendance and attendance.is_retroactive_edit)

    def get_marked_at(self, obj):
        attendance = obj["attendance"]
        return attendance.marked_at if attendance else None
