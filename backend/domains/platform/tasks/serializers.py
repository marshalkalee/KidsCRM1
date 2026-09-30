from rest_framework import serializers

from .models import Task


class TaskSerializer(serializers.ModelSerializer):
    assigned_to_name = serializers.CharField(
        source="assigned_to.full_name", read_only=True, default=None
    )
    created_by_name = serializers.CharField(
        source="created_by.full_name", read_only=True, default=None
    )
    type_display = serializers.CharField(source="get_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    child_name = serializers.CharField(source="child.full_name", read_only=True, default=None)
    lead_name = serializers.CharField(source="lead.parent_name", read_only=True, default=None)

    class Meta:
        model = Task
        fields = [
            "id",
            "type",
            "type_display",
            "status",
            "status_display",
            "source",
            "title",
            "description",
            "closing_comment",
            "due_at",
            "assigned_to",
            "assigned_to_name",
            "created_by",
            "created_by_name",
            "lead",
            "lead_name",
            "child",
            "child_name",
            "branch",
            "created_at",
        ]
        read_only_fields = ["source", "created_by", "closing_comment"]
