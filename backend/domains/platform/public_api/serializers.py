"""
Ответы публичного API v1 — обязательство (docs/public-api.md). Поля
перечислены явно и не повторяют модели: модель можно менять, ответ — нет.
Новое поле можно добавить; убрать, переименовать или поменять тип — только
в v2.

Чего нет намеренно: телефоны и контакты родителей, медицинские заметки,
причины ухода, скидки и комментарии сотрудников — ключ попадает в чужой
код и логи, ПДн несовершеннолетних наружу без нужды не отдаём (ТЗ п. 10.3).
"""

from rest_framework import serializers

from domains.money.payments.models import Payment
from domains.money.subscriptions.models import Subscription
from domains.people.clients.models import Child
from domains.scheduling.attendance.models import Attendance
from domains.scheduling.groups.models import Group
from domains.scheduling.schedule.models import Lesson


class RefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class ChildSerializer(serializers.ModelSerializer):
    group_ids = serializers.SerializerMethodField()

    class Meta:
        model = Child
        fields = ["id", "full_name", "birth_date", "status", "group_ids"]

    def get_group_ids(self, child) -> list[str]:
        return [str(m.group_id) for m in getattr(child, "active_memberships", [])]


class GroupSerializer(serializers.ModelSerializer):
    branch = RefSerializer()
    direction = RefSerializer(allow_null=True)

    class Meta:
        model = Group
        fields = ["id", "name", "branch", "direction", "capacity", "age_min", "age_max", "status"]


class LessonSerializer(serializers.ModelSerializer):
    branch_id = serializers.SerializerMethodField()
    room = RefSerializer(allow_null=True)

    class Meta:
        model = Lesson
        fields = ["id", "group_id", "branch_id", "room", "starts_at", "ends_at", "status"]

    def get_branch_id(self, lesson) -> str | None:
        if lesson.group_id:
            return str(lesson.group.branch_id)
        return str(lesson.room.branch_id) if lesson.room_id else None


class AttendanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attendance
        fields = ["id", "lesson_id", "child_id", "status", "marked_at"]


class SubscriptionSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="subscription_type_version.name")
    sessions_remaining = serializers.IntegerField(source="sessions_remaining_cache")

    class Meta:
        model = Subscription
        fields = [
            "id",
            "child_id",
            "branch_id",
            "name",
            "starts_on",
            "ends_on",
            "status",
            "sessions_remaining",
            "price",
        ]


class PaymentSerializer(serializers.ModelSerializer):
    child_id = serializers.UUIDField(source="subscription.child_id")

    class Meta:
        model = Payment
        fields = ["id", "subscription_id", "child_id", "amount", "method", "status", "paid_at"]


class LeadCreateSerializer(serializers.Serializer):
    parent_name = serializers.CharField(max_length=255)
    phone = serializers.CharField(max_length=32)
    child_name = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    child_age = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=25, default=None
    )
    branch_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    direction_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    comment = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class LeadCreatedSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    status = serializers.CharField()
