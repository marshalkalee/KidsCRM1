from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from domains.platform.core.permissions import IsOwnerOrManager, IsStaffOfOrganization
from domains.platform.core.viewsets import TenantModelViewSet
from domains.scheduling.schedule_templates.services import (
    cancel_future_lessons,
    generate_lessons_from_template,
    get_affected_future_lessons,
)

from .models import ScheduleTemplate, ScheduleTemplateSlot
from .serializers import ScheduleTemplateSerializer, ScheduleTemplateSlotSerializer


class ScheduleTemplateViewSet(TenantModelViewSet):
    serializer_class = ScheduleTemplateSerializer

    def get_permissions(self):
        if self.action in ["create", "update", "partial_update", "destroy"]:
            return [IsOwnerOrManager()]
        return [IsStaffOfOrganization()]

    def get_queryset(self):
        qs = (
            ScheduleTemplate.objects.for_tenant(self.request.organization)
            .prefetch_related("slots__room", "slots__teacher")
            .select_related("group")
        )
        group_id = self.request.query_params.get("group")
        if group_id:
            qs = qs.filter(group_id=group_id)
        return qs

    @action(detail=True, methods=["post"])
    def generate(self, request, pk=None):
        template = self.get_object()
        dry_run = request.data.get("dry_run", False)

        if dry_run:
            result = generate_lessons_from_template(template, dry_run=True)
            return Response(
                {
                    "created_count": len(result["created"]),
                    "skipped_count": result["skipped"],
                    "dry_run": True,
                    "lessons": result["created"],
                }
            )

        from domains.scheduling.schedule_templates.tasks import generate_lessons_for_template

        task = generate_lessons_for_template.delay(str(template.id))
        return Response(
            {
                "task_id": task.id,
                "message": "Генерация запущена в фоне.",
                "dry_run": False,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=["get"])
    def affected_lessons(self, request, pk=None):
        """Список будущих занятий которые затронет смена шаблона."""
        template = self.get_object()
        lessons = get_affected_future_lessons(template)
        return Response(
            {
                "count": lessons.count(),
                "lessons": [
                    {
                        "id": str(lesson.id),
                        "starts_at": lesson.starts_at,
                        "group": str(lesson.group),
                    }
                    for lesson in lessons[:20]
                ],
            }
        )

    @action(detail=True, methods=["post"])
    def cancel_future(self, request, pk=None):
        """Отменить будущие занятия без ручных правок — перед сменой шаблона."""
        template = self.get_object()
        count, _ = cancel_future_lessons(template)
        return Response({"cancelled_count": count})


class ScheduleTemplateSlotViewSet(TenantModelViewSet):
    serializer_class = ScheduleTemplateSlotSerializer

    def get_permissions(self):
        return [IsOwnerOrManager()]

    def get_queryset(self):
        return (
            ScheduleTemplateSlot.objects.for_tenant(self.request.organization)
            .select_related("room", "teacher", "template__group")
            .filter(template_id=self.kwargs.get("template_pk"))
        )

    def perform_create(self, serializer):
        template = ScheduleTemplate.objects.for_tenant(self.request.organization).get(
            pk=self.kwargs["template_pk"]
        )
        serializer.save(
            organization=self.request.organization,
            template=template,
        )
