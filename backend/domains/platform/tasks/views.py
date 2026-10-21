import uuid

from django.db.models import Count, F, Q
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from domains.platform.core.audit import AuditLog
from domains.platform.core.permissions import (
    IsNotTeacher,
    IsOwnerOrManager,
    IsOwnerOrManagerOrAdmin,
    IsStaffOfOrganization,
)
from domains.platform.users.models import User

from .models import Task, TaskComment
from .serializers import TaskCommentSerializer, TaskHistorySerializer, TaskSerializer
from .services import cancel_task, complete_task, visible_tasks
from .timeline import build_timeline, can_edit_comment

# Кто ставит и передаёт задачи; остальные только выполняют свои.
TASK_MANAGERS = (User.Role.OWNER, User.Role.MANAGER, User.Role.ADMIN)

# Сколько закрытых задач отдаём во вкладку «Задачи» карточки ребёнка.
CLOSED_HISTORY_LIMIT = 100

# Что видно в ленте карточки задачи (TRU-184): кто передал и куда перенёс срок.
AUDITED_FIELDS = ("assigned_to", "due_at")


def with_comments_count(qs):
    """Счётчик комментариев у задачи в списке (TRU-184) — одним запросом."""
    return qs.annotate(
        comments_count=Count("comments", filter=Q(comments__deleted_at__isnull=True))
    )


def _raw(task, field):
    return task.assigned_to_id if field == "assigned_to" else task.due_at


def _audit_value(task, field):
    if field == "assigned_to":
        return task.assigned_to.full_name if task.assigned_to else None
    return task.due_at.isoformat() if task.due_at else None


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
        if self.action == "create":
            return [IsOwnerOrManagerOrAdmin()]
        # Свои задачи видит, закрывает и переносит любой сотрудник, кому их
        # поручили (бухгалтер, преподаватель); остальное — _check_can_change.
        # Комментарии и лента (TRU-184) — всем, кто видит задачу.
        if self.action in (
            "list",
            "retrieve",
            "update",
            "partial_update",
            "complete",
            "cancel",
            "comments",
            "comment_detail",
            "timeline",
        ):
            return [IsStaffOfOrganization()]
        return [IsNotTeacher()]

    def _check_can_change(self, task, fields=None):
        """Бухгалтер и преподаватель меняют только свои задачи и только срок
        («На завтра»); передать или поручить — руководитель и администратор."""
        user = self.request.user
        if user.role in TASK_MANAGERS:
            return
        if task.assigned_to_id != user.id:
            raise PermissionDenied("Это не ваша задача.")
        if fields is not None and set(fields) - {"due_at"}:
            raise PermissionDenied("Можно только перенести срок.")

    def get_queryset(self):
        qs = with_comments_count(visible_tasks(self.request.user)).select_related(
            "assigned_to",
            "created_by",
            "lead",
            "child",
            "branch",
        )
        status_param = self.request.query_params.get("status")
        type_param = self.request.query_params.get("type")
        assignee_param = self.request.query_params.get("assigned_to")
        branch_param = self.request.query_params.get("branch")
        if status_param:
            qs = qs.filter(status=status_param)
        if type_param:
            qs = qs.filter(type=type_param)
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
        task = serializer.save(
            organization=self.request.user.organization,
            created_by=self.request.user,
            source=Task.Source.MANUAL,
        )
        AuditLog.record(
            actor=self.request.user,
            action=AuditLog.Action.CREATE,
            entity=task,
            after={
                "title": task.title,
                "assigned_to": task.assigned_to.full_name if task.assigned_to else None,
                "due_at": task.due_at.isoformat() if task.due_at else None,
            },
        )

    def partial_update(self, request, *args, **kwargs):
        """Передача (ТЗ п. 5.2, TRU-109) и перенос срока (TRU-184) пишутся в
        аудит-лог — из него строится лента карточки задачи. Остальные
        изменения (заголовок, описание) — нет."""
        instance = self.get_object()
        self._check_can_change(instance, request.data.keys())
        old = {field: _raw(instance, field) for field in AUDITED_FIELDS}
        old_values = {field: _audit_value(instance, field) for field in AUDITED_FIELDS}
        response = super().partial_update(request, *args, **kwargs)
        instance.refresh_from_db()
        changed = [
            field
            for field in AUDITED_FIELDS
            if field in request.data and _raw(instance, field) != old[field]
        ]
        if changed:
            AuditLog.record(
                actor=request.user,
                action=AuditLog.Action.UPDATE,
                entity=instance,
                before={field: old_values[field] for field in changed},
                after={field: _audit_value(instance, field) for field in changed},
            )
        return response

    def _record_close(self, task, action):
        AuditLog.record(
            actor=self.request.user,
            action=action,
            entity=task,
            before={"status": Task.Status.OPEN},
            after={"status": task.status, "closing_comment": task.closing_comment},
        )

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        task = self.get_object()
        self._check_can_change(task)
        complete_task(task, actor=request.user, comment=request.data.get("comment", ""))
        self._record_close(task, AuditLog.Action.UPDATE)
        return Response(TaskSerializer(task).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        task = self.get_object()
        self._check_can_change(task)
        cancel_task(task, actor=request.user, comment=request.data.get("comment", ""))
        self._record_close(task, AuditLog.Action.CANCEL)
        return Response(TaskSerializer(task).data)

    @action(detail=True, methods=["get", "post"])
    def comments(self, request, pk=None):
        """Комментарии к задаче (TRU-184): читают и пишут все, кто видит
        задачу (get_object → visible_tasks: исполнитель, автор по филиалу,
        руководители по Д36/Д37). Чужая задача — 404."""
        task = self.get_object()
        if request.method == "GET":
            comments = (
                TaskComment.objects.for_tenant(task.organization)
                .filter(task=task)
                .select_related("author")
            )
            return Response(
                TaskCommentSerializer(comments, many=True, context={"request": request}).data
            )
        serializer = TaskCommentSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save(organization=task.organization, task=task, author=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=["patch", "delete"],
        url_path=r"comments/(?P<comment_id>[0-9a-f-]{36})",
    )
    def comment_detail(self, request, pk=None, comment_id=None):
        """Править и удалять — только автор и только первые 15 минут."""
        task = self.get_object()
        comment = get_object_or_404(
            TaskComment.objects.for_tenant(task.organization).filter(task=task), pk=comment_id
        )
        if comment.author_id != request.user.id:
            raise PermissionDenied("Это не ваш комментарий.")
        if not can_edit_comment(comment, request.user):
            raise PermissionDenied("Комментарий можно изменить только в течение 15 минут.")
        if request.method == "DELETE":
            comment.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        serializer = TaskCommentSerializer(
            comment, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(edited_at=timezone.now())
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def timeline(self, request, pk=None):
        """Лента карточки задачи (TRU-184): комментарии и события журнала
        одной лентой по времени, старые сверху; текст событий — готовый."""
        task = self.get_object()
        return Response({"items": build_timeline(task, request.user)})

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
        # Название типа — с сервера: новый тип не покажется сырым ключом.
        labels = dict(Task.Type.choices)
        for row in by_type:
            row["label"] = labels.get(row["type"], row["type"])

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
            with_comments_count(visible_tasks(request.user))
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
