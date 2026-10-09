from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import filters, status
from rest_framework.decorators import action
from rest_framework.response import Response

from domains.platform.core.active_branch import branch_scope
from domains.platform.core.permissions import (
    IsOwnerOrManager,
    IsStaffOfOrganization,
)
from domains.platform.core.viewsets import TenantModelViewSet
from domains.scheduling.schedule_templates.models import ScheduleTemplate, ScheduleTemplateSlot
from domains.scheduling.schedule_templates.services import (
    cancel_future_lessons,
    generate_lessons_from_template,
)

from . import queries
from .models import Group, GroupMembership
from .serializers import (
    GroupMembershipSerializer,
    GroupScheduleSerializer,
    GroupSerializer,
)


class GroupViewSet(TenantModelViewSet):
    serializer_class = GroupSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "direction__name", "branch__name"]
    ordering_fields = ["name", "capacity", "status", "created_at"]
    ordering = ["name"]

    def get_permissions(self):
        if self.action in ["create", "update", "partial_update", "destroy"] or (
            self.action == "fixed_schedule" and self.request.method != "GET"
        ):
            return [IsOwnerOrManager()]
        return [IsStaffOfOrganization()]

    def get_queryset(self):
        qs = queries.with_members_count(
            Group.objects.for_tenant(self.request.user.organization)
            .select_related("branch", "direction")
            .prefetch_related(
                "teachers",
                "schedule_templates__slots__room",
                "schedule_templates__slots__teacher",
            )
            .annotate(teachers_count=Count("teachers", distinct=True))
        )
        user = self.request.user
        if user.role == "teacher":
            qs = qs.filter(teachers=user)

        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        scope = branch_scope(self.request, self.request.query_params.get("branch"))
        if scope is not None:
            qs = qs.filter(branch_id__in=scope)

        direction_id = self.request.query_params.get("direction")
        if direction_id:
            qs = qs.filter(direction_id=direction_id)

        teacher_id = self.request.query_params.get("teacher")
        if teacher_id:
            qs = qs.filter(teachers__id=teacher_id)

        if self.request.query_params.get("for_enrollment"):
            qs = qs.filter(status=Group.Status.ACTIVE)

        return qs

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)

    def perform_destroy(self, instance):
        instance.status = Group.Status.CLOSED
        instance.save(update_fields=["status", "updated_at"])

    @action(detail=True, methods=["get"])
    def members(self, request, pk=None):
        group = self.get_object()
        memberships = (
            GroupMembership.objects.for_tenant(request.user.organization)
            .filter(group=group, left_at__isnull=True)
            .select_related("child")
            .order_by("child__full_name")
        )
        serializer = GroupMembershipSerializer(memberships, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def add_member(self, request, pk=None):
        group = self.get_object()
        serializer = GroupMembershipSerializer(
            data={**request.data, "group": group.id},
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def remove_member(self, request, pk=None):
        group = self.get_object()
        child_id = request.data.get("child_id")
        left_at = request.data.get("left_at")

        membership = (
            GroupMembership.objects.for_tenant(request.user.organization)
            .filter(
                group=group,
                child_id=child_id,
                left_at__isnull=True,
            )
            .first()
        )

        if not membership:
            return Response(
                {"detail": "Ребёнок не найден в этой группе."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Без даты — «вышел сегодня» (раньше left_at=None молча ничего не менял).
        membership.left_at = left_at or timezone.localdate()
        membership.save(update_fields=["left_at", "updated_at"])
        return Response(GroupMembershipSerializer(membership).data)

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        group = self.get_object()
        memberships = (
            GroupMembership.objects.for_tenant(request.user.organization)
            .filter(group=group)
            .select_related("child")
            .order_by("-joined_at")
        )
        serializer = GroupMembershipSerializer(memberships, many=True)
        return Response(serializer.data)

    def _active_schedule_templates(self, group, *, for_update=False):
        today = timezone.localdate()
        queryset = ScheduleTemplate.objects.for_tenant(self.request.user.organization).filter(
            group=group,
            valid_from__lte=today,
        )
        if for_update:
            queryset = queryset.select_for_update()
        return (
            queryset.filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
            .prefetch_related("slots__room", "slots__teacher")
            .order_by("-valid_from")
        )

    def _current_schedule_template(self, group):
        return self._active_schedule_templates(group).first()

    @staticmethod
    def _schedule_payload(template):
        if template is None:
            return {"id": None, "generate_weeks_ahead": 8, "slots": []}
        return {
            "id": str(template.id),
            "generate_weeks_ahead": template.generate_weeks_ahead,
            "slots": [
                {
                    "id": str(slot.id),
                    "weekday": slot.weekday,
                    "start_time": slot.start_time.strftime("%H:%M"),
                    "duration_minutes": slot.duration_minutes,
                    "room": str(slot.room_id) if slot.room_id else None,
                    "room_name": slot.room.name if slot.room else None,
                    "teacher": str(slot.teacher_id) if slot.teacher_id else None,
                    "teacher_name": slot.teacher.full_name if slot.teacher else None,
                }
                for slot in template.slots.all()
            ],
        }

    @action(detail=True, methods=["get", "put"], url_path="fixed-schedule")
    def fixed_schedule(self, request, pk=None):
        """Постоянные недельные слоты группы и генерация будущих занятий."""
        group = self.get_object()
        if request.method == "GET":
            return Response(self._schedule_payload(self._current_schedule_template(group)))

        serializer = GroupScheduleSerializer(
            data=request.data,
            context={"request": request, "group": group},
        )
        serializer.is_valid(raise_exception=True)
        slots_data = serializer.validated_data["slots"]

        with transaction.atomic():
            active_templates = list(self._active_schedule_templates(group, for_update=True))
            template = active_templates[0] if active_templates else None
            for active_template in active_templates:
                cancel_future_lessons(active_template)
            # Старые пересекающиеся шаблоны не должны снова создавать занятия ночью.
            for stale_template in active_templates[1:]:
                stale_template.delete()

            if not slots_data:
                if template is not None:
                    for slot in template.slots.all():
                        slot.delete()
                    template.delete()
                return Response(
                    {
                        "id": None,
                        "generate_weeks_ahead": serializer.validated_data["generate_weeks_ahead"],
                        "slots": [],
                        "generated_count": 0,
                        "conflicts_count": 0,
                    }
                )

            if template is None:
                template = ScheduleTemplate.objects.create(
                    organization=request.user.organization,
                    group=group,
                    valid_from=timezone.localdate(),
                    generate_weeks_ahead=serializer.validated_data["generate_weeks_ahead"],
                )
                existing_slots = {}
            else:
                template.generate_weeks_ahead = serializer.validated_data["generate_weeks_ahead"]
                template.valid_until = None
                template.save(update_fields=["generate_weeks_ahead", "valid_until", "updated_at"])
                existing_slots = {str(slot.id): slot for slot in template.slots.all()}

            kept_ids = set()
            selected_teachers = []
            for slot_data in slots_data:
                slot_id = str(slot_data.pop("id", ""))
                slot = existing_slots.get(slot_id)
                if slot is None:
                    slot = ScheduleTemplateSlot(
                        organization=request.user.organization,
                        template=template,
                    )
                else:
                    kept_ids.add(slot_id)
                for field in [
                    "weekday",
                    "start_time",
                    "duration_minutes",
                    "room",
                    "teacher",
                ]:
                    setattr(slot, field, slot_data.get(field))
                slot.save()
                if slot.teacher_id:
                    selected_teachers.append(slot.teacher)

            for slot_id, slot in existing_slots.items():
                if slot_id not in kept_ids:
                    slot.delete()

            if selected_teachers:
                group.teachers.add(*selected_teachers)

            result = generate_lessons_from_template(template)

        template = (
            ScheduleTemplate.objects.for_tenant(request.user.organization)
            .prefetch_related("slots__room", "slots__teacher")
            .get(pk=template.pk)
        )
        return Response(
            {
                **self._schedule_payload(template),
                "generated_count": len(result["created"]),
                "conflicts_count": len(result["conflicts"]),
            }
        )
