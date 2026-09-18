from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from domains.platform.core.audit import AuditLog
from domains.platform.core.permissions import IsStaffOfOrganization


class AuditLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.full_name", read_only=True)
    entity_type = serializers.CharField(source="content_type.model", read_only=True)

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "actor_name",
            "action",
            "entity_type",
            "object_id",
            "before",
            "after",
            "created_at",
        ]


class AuditLogView(APIView):
    permission_classes = [IsStaffOfOrganization]

    def get(self, request):
        qs = AuditLog.objects.filter(organization=request.organization)

        entity_type = request.query_params.get("entity_type")
        object_id = request.query_params.get("object_id")

        if entity_type:
            qs = qs.filter(content_type__model=entity_type)
        if object_id:
            qs = qs.filter(object_id=object_id)

        serializer = AuditLogSerializer(qs[:100], many=True)
        return Response(serializer.data)
