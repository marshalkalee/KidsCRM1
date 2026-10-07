import uuid

from django.db.models import Count, F, Q
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from domains.platform.core.audit import AuditLog
from domains.platform.core.permissions import (
    IsNotTeacher,
    IsOwnerOrManager,
    IsOwnerOrManagerOrAdmin,
)

from .models import Task
from .serializers import TaskHistorySerializer, TaskSerializer
from .services import cancel_task, complete_task, visible_tasks

# Сколько закрытых задач отдаём во вкладку «Задачи» карточки ребёнка.
CLOSED_HISTORY_LIMIT = 100


class TaskViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = TaskSerializer

    def get_permissions(self):
        if self.action == "escalation":
            return [IsOwnerOrManager()]
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
        lead_param = self.request.query_params.get("lead")
        child_param = self.request.query_params.get("child")
        if lead_param:
            qs = qs.filter(lead_id=lead_param)
        if child_param:
            qs = qs.filter(child_id=child_param)
        return qs

    def perform_create(self, serializer):
        serializer.save(
            organization=self.request.user.organization,
            created_by=self.request.user,
            source=Task.Source.MANUAL,
        )

    def partial_update(self, request, *args, **kwargs):
        """Переназначение пишется в аудит-лог (ТЗ п. 5.2, TRU-109) — только
        смена assigned_to, не любое изменение (например, дедлайна)."""
        instance = self.get_object()
        old_assignee = instance.assigned_to
        response = super().partial_update(request, *args, **kwargs)
        instance.refresh_from_db()
        if "assigned_to" in request.data and instance.assigned_to_id != (
            old_assignee.id if old_assignee else None
        ):
            AuditLog.record(
                actor=request.user,
                action=AuditLog.Action.UPDATE,
                entity=instance,
                before={"assigned_to": old_assignee.full_name if old_assignee else None},
                after={
                    "assigned_to": instance.assigned_to.full_name if instance.assigned_to else None
                },
            )
        return response

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
    def escalation(self, request):
        """Экран эскалации управляющего (ТЗ п. 5.2, TRU-109): просроченные
        задачи по филиалам управляющего, по сотруднику и по типу. Только
        факты — без рейтинга/оценки сотрудников."""
        base = visible_tasks(request.user)
        branch_param = request.query_params.get("branch")
        if branch_param:
            base = base.filter(branch_id=branch_param)

        overdue = base.filter(status=Task.Status.OPEN, due_at__lt=timezone.now()).select_related(
            "assigned_to", "branch"
        )
        open_counts = {
            row["assigned_to_id"]: row["open_count"]
            for row in base.filter(status=Task.Status.OPEN)
            .values("assigned_to_id")
            .annotate(open_count=Count("id"))
        }

        by_employee = {}
        for task in overdue:
            key = task.assigned_to_id
            row = by_employee.setdefault(
                key,
                {
                    "assigned_to": str(key) if key else None,
                    "name": task.assigned_to.full_name if task.assigned_to else "Не назначено",
                    "open": open_counts.get(key, 0),
                    "overdue": 0,
                    "oldest_due_at": None,
                },
            )
            row["overdue"] += 1
            if row["oldest_due_at"] is None or task.due_at < row["oldest_due_at"]:
                row["oldest_due_at"] = task.due_at

        for row in by_employee.values():
            row["oldest_due_at"] = (
                row["oldest_due_at"].isoformat() if row["oldest_due_at"] else None
            )

        by_type = list(overdue.values("type").annotate(count=Count("id")).order_by("-count"))

        return Response(
            {
                "by_employee": sorted(by_employee.values(), key=lambda r: r["name"]),
                "by_type": by_type,
                "total_overdue": overdue.count(),
            }
        )

    @action(detail=False, methods=["get"], url_path="for-child")
    def for_child(self, request):
        """Вкладка «Задачи» карточки ребёнка (ТЗ п. 4.1, TRU-112): задачи по
        самому ребёнку и по его заявкам — до конвертации работа велась по
        заявке, и обрывать историю на этой границе неправильно. Права те же,
        что у списка задач: только то, что пользователь видит (филиалы)."""
        try:
            child_id = uuid.UUID(request.query_params.get("child", ""))
        except ValueError:
            return Response({"detail": "Укажите child."}, status=400)

        tasks = (
            visible_tasks(request.user)
            .filter(
                Q(child_id=child_id)
                | Q(lead__converted_child_id=child_id)
                | Q(lead__child_id=child_id)
            )
            .select_related("assigned_to", "created_by", "lead")
        )
        open_tasks = tasks.filter(status=Task.Status.OPEN).order_by(
            F("due_at").asc(nulls_last=True), "created_at"
        )
        closed_tasks = tasks.exclude(status=Task.Status.OPEN)
        return Response(
            {
                "open": TaskHistorySerializer(open_tasks, many=True).data,
                "closed": TaskHistorySerializer(
                    closed_tasks.order_by("-updated_at")[:CLOSED_HISTORY_LIMIT], many=True
                ).data,
                "closed_total": closed_tasks.count(),
            }
        )
