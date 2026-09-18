from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from domains.platform.core.mixins import TenantCreateMixin

from .models import Group, GroupMembership


class GroupSerializer(TenantCreateMixin, serializers.ModelSerializer):
    teachers_count = serializers.IntegerField(read_only=True)
    members_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Group
        fields = [
            "id",
            "name",
            "branch",
            "direction",
            "teachers",
            "capacity",
            "age_min",
            "age_max",
            "status",
            "teachers_count",
            "members_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, attrs):
        if attrs.get("age_min") and attrs.get("age_max"):
            if attrs["age_min"] > attrs["age_max"]:
                raise serializers.ValidationError(
                    {"age_min": _("Возраст «от» не может быть больше «до».")}
                )
        return attrs


class GroupMembershipSerializer(TenantCreateMixin, serializers.ModelSerializer):
    child_name = serializers.CharField(source="child.full_name", read_only=True)
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = GroupMembership
        fields = [
            "id",
            "group",
            "child",
            "child_name",
            "joined_at",
            "left_at",
            "note",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate(self, attrs):
        if attrs.get("left_at") and attrs.get("joined_at"):
            if attrs["left_at"] < attrs["joined_at"]:
                raise serializers.ValidationError(
                    {"left_at": _("Дата выхода не может быть раньше даты вступления.")}
                )
        return attrs
