from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from domains.platform.core.permissions import IsStaffOfOrganization

from .models import Attendance
from .serializers import AttendanceMarkSerializer, AttendanceSerializer


class AttendanceViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Только чтение + один вход на запись — action `mark` (см.
    AttendanceMarkSerializer). Обычные create/update здесь намеренно не
    открыты: они позволили бы сменить status в обход Attendance.mark() и
    разошлись бы со списанием с абонемента (SubscriptionService не был бы
    вызван)."""

    serializer_class = AttendanceSerializer
    permission_classes = [IsAuthenticated, IsStaffOfOrganization]

    def get_queryset(self):
        qs = Attendance.objects.for_tenant(self.request.organization).select_related(
            "child", "lesson", "marked_by"
        )
        lesson_id = self.request.query_params.get("lesson")
        if lesson_id:
            qs = qs.filter(lesson_id=lesson_id)
        child_id = self.request.query_params.get("child")
        if child_id:
            qs = qs.filter(child_id=child_id)
        return qs

    @action(detail=False, methods=["post"])
    def mark(self, request):
        serializer = AttendanceMarkSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        lesson = serializer.validated_data["lesson"]
        child = serializer.validated_data["child"]
        status_value = serializer.validated_data["status"]
        absence_reason = serializer.validated_data.get("absence_reason", "")

        attendance, _created = Attendance.objects.get_or_create(
            lesson=lesson,
            child=child,
            defaults={
                "organization": self.request.organization,
                "status": Attendance.Status.ABSENT,
            },
        )
        attendance.mark(status_value, actor=request.user, absence_reason=absence_reason)
        return Response(AttendanceSerializer(attendance, context={"request": request}).data)
