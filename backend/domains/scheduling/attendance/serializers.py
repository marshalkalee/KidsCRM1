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
            "marked_by",
            "marked_at",
            "created_at",
            "updated_at",
        ]


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
