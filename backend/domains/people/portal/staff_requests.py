from django.db.models import Q
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from domains.platform.core.active_branch import get_active_branch
from domains.platform.core.permissions import IsOwnerOrManagerOrAdmin
from domains.platform.users.models import User

from .lesson_requests import _spots_left
from .models import ParentLessonRequest
from .request_processing import (
    RequestProcessingError,
    approve_parent_request,
    reject_parent_request,
)


class StaffParentRequestSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source="get_type_display", read_only=True)
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    cancel_reason_display = serializers.CharField(
        source="get_cancel_reason_display", read_only=True
    )
    child_name = serializers.CharField(source="child.full_name", read_only=True)
    processed_by_name = serializers.CharField(
        source="processed_by.full_name", read_only=True, default=None
    )
    lesson = serializers.SerializerMethodField()
    spots_available_now = serializers.SerializerMethodField()

    class Meta:
        model = ParentLessonRequest
        fields = [
            "id",
            "type",
            "type_display",
            "kind",
            "kind_display",
            "status",
            "status_display",
            "child",
            "child_name",
            "lesson",
            "comment",
            "cancel_reason",
            "cancel_reason_display",
            "notice_hours_required",
            "notice_is_timely",
            "will_be_charged",
            "spots_available_at_request",
            "spots_available_now",
            "rejection_reason",
            "processed_by_name",
            "processed_at",
            "created_at",
        ]

    def get_spots_available_now(self, obj):
        return _spots_left(obj.lesson) if obj.type == ParentLessonRequest.Type.ENROLL else None

    def get_lesson(self, obj):
        lesson = obj.lesson
        branch = lesson.group.branch if lesson.group_id else getattr(lesson.room, "branch", None)
        return {
            "id": lesson.id,
            "name": lesson.group.name if lesson.group_id else "Индивидуальное занятие",
            "starts_at": lesson.starts_at,
            "ends_at": lesson.ends_at,
            "status": lesson.status,
            "branch_id": branch.id if branch else None,
            "branch_name": branch.name if branch else None,
            "room_name": lesson.room.name if lesson.room else None,
            "teacher_name": lesson.teacher.full_name if lesson.teacher else None,
        }


class BulkActionSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=100)
    decision = serializers.ChoiceField(choices=["approve", "reject"])
    reason = serializers.CharField(required=False, allow_blank=True, max_length=1000)

    def validate(self, attrs):
        if attrs["decision"] == "reject" and not attrs.get("reason", "").strip():
            raise serializers.ValidationError({"reason": "Укажите причину отказа."})
        return attrs


def visible_parent_requests(user):
    qs = ParentLessonRequest.objects.for_tenant(user.organization)
    if user.role == User.Role.OWNER:
        return qs
    branch_ids = list(user.branches.values_list("id", flat=True))
    if not branch_ids:
        return qs
    return qs.filter(
        Q(lesson__group__branch_id__in=branch_ids) | Q(lesson__room__branch_id__in=branch_ids)
    )


class ParentRequestViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = StaffParentRequestSerializer
    permission_classes = [IsOwnerOrManagerOrAdmin]

    def get_queryset(self):
        qs = visible_parent_requests(self.request.user).select_related(
            "child",
            "lesson__group__branch",
            "lesson__room__branch",
            "lesson__teacher",
            "processed_by",
        )
        active = get_active_branch(self.request)
        branch_id = self.request.query_params.get("branch") or (active.id if active else None)
        if branch_id:
            qs = qs.filter(
                Q(lesson__group__branch_id=branch_id) | Q(lesson__room__branch_id=branch_id)
            )
        for field in ("status", "type", "kind"):
            value = self.request.query_params.get(field)
            if value:
                qs = qs.filter(**{field: value})
        return qs.order_by("-created_at")

    def _get_scoped(self, pk):
        # Actions do not carry the list's branch filter.  Using get_queryset()
        # here silently fell back to the globally active branch, so a request
        # opened through another branch filter was visible but could not be
        # approved.  Role/tenant branch access is the authorization boundary;
        # the active branch is only a list filter.
        return visible_parent_requests(self.request.user).filter(pk=pk).first()

    def _process(self, request, pk, decision):
        if self._get_scoped(pk) is None:
            return Response({"detail": "Запрос не найден."}, status=status.HTTP_404_NOT_FOUND)
        try:
            if decision == "approve":
                result = approve_parent_request(pk, actor=request.user)
            else:
                result = reject_parent_request(
                    pk, actor=request.user, reason=request.data.get("reason", "")
                )
        except RequestProcessingError as exc:
            return Response({"detail": str(exc)}, status=exc.status_code)
        return Response(self.get_serializer(result).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._process(request, pk, "approve")

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._process(request, pk, "reject")

    @action(detail=False, methods=["post"])
    def bulk(self, request):
        payload = BulkActionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        action_queryset = visible_parent_requests(request.user)
        visible_ids = set(
            action_queryset.filter(pk__in=payload.validated_data["ids"]).values_list(
                "id", flat=True
            )
        )
        selected_types = set(
            action_queryset.filter(pk__in=visible_ids).values_list("type", flat=True)
        )
        if len(selected_types) > 1:
            return Response(
                {"detail": "Для массовой обработки выберите запросы одного типа."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        processed = []
        errors = []
        for request_id in payload.validated_data["ids"]:
            if request_id not in visible_ids:
                errors.append({"id": str(request_id), "detail": "Запрос не найден."})
                continue
            try:
                if payload.validated_data["decision"] == "approve":
                    approve_parent_request(request_id, actor=request.user)
                else:
                    reject_parent_request(
                        request_id,
                        actor=request.user,
                        reason=payload.validated_data.get("reason", ""),
                    )
                processed.append(str(request_id))
            except RequestProcessingError as exc:
                errors.append({"id": str(request_id), "detail": str(exc)})
        return Response(
            {"processed": processed, "errors": errors, "processed_count": len(processed)},
            status=status.HTTP_200_OK,
        )
