from django.db.models import Count
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from domains.platform.core.permissions import IsNotTeacher, IsOwnerOrManagerOrAdmin

from .models import Task
from .serializers import TaskSerializer
from .services import cancel_task, complete_task, visible_tasks


class TaskViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = TaskSerializer

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "complete", "cancel"):
            return [IsOwnerOrManagerOrAdmin()]
        return [IsNotTeacher()]

    def get_queryset(self):
        qs = visible_tasks(self.request.user).select_related(
            "assigned_to",
            "created_by",
            "lead",
            "child",
            "branch",
        )
        status_param = self.request.query_params.get("status")
        assignee_param = self.request.query_params.get("assigned_to")
        branch_param = self.request.query_params.get("branch")
        if status_param:
            qs = qs.filter(status=status_param)
        if assignee_param:
            qs = qs.filter(assigned_to_id=assignee_param)
        if branch_param:
            qs = qs.filter(branch_id=branch_param)
        return qs

    def perform_create(self, serializer):
        serializer.save(
            organization=self.request.user.organization,
            created_by=self.request.user,
            source=Task.Source.MANUAL,
        )

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        task = self.get_object()
        complete_task(task, actor=request.user, comment=request.data.get("comment", ""))
        return Response(TaskSerializer(task).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        task = self.get_object()
        cancel_task(task, actor=request.user, comment=request.data.get("comment", ""))
        return Response(TaskSerializer(task).data)

    @action(detail=False, methods=["get"])
    def by_assignee(self, request):
        """Счётчики открытых задач по сотрудникам — для эскалации у
        управляющего (ТЗ п. 2)."""
        counts = (
            visible_tasks(request.user)
            .filter(status=Task.Status.OPEN)
            .values("assigned_to_id", "assigned_to__full_name")
            .annotate(open_count=Count("id"))
            .order_by("-open_count")
        )
        return Response(list(counts))
