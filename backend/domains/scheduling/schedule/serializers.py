from django.utils import timezone
from rest_framework import serializers

from domains.people.clients.models import Child
from domains.platform.core.mixins import TenantCreateMixin

from .conflicts import find_conflicting_lessons
from .models import Lesson, LessonEnrollment


class LessonSerializer(TenantCreateMixin, serializers.ModelSerializer):
    starts_at_local = serializers.SerializerMethodField()
    ends_at_local = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    rescheduled_to_id = serializers.SerializerMethodField()
    # TRU-48: причина отмены — справочник + комментарий.
    cancel_reason_category_display = serializers.CharField(
        source="get_cancel_reason_category_display", read_only=True
    )
    # TRU-46: конфликт по залу/преподавателю — предупреждение, не запрет,
    # поэтому виден прямо в календаре (не только в момент создания).
    has_conflict = serializers.SerializerMethodField()
    conflicting_lesson_ids = serializers.SerializerMethodField()

    # Поля для календаря — считаются из уже загруженных select_related/
    # prefetch_related объектов во view, доп. запросов не делают (см.
    # LessonViewSet.get_queryset).
    group_name = serializers.SerializerMethodField()
    direction_id = serializers.SerializerMethodField()
    direction_color = serializers.SerializerMethodField()
    room_name = serializers.SerializerMethodField()
    teacher_name = serializers.SerializerMethodField()
    capacity = serializers.SerializerMethodField()
    enrolled_count = serializers.SerializerMethodField()

    # TRU-47: индивидуальное занятие (group=None) — дети привязаны напрямую.
    is_individual = serializers.BooleanField(read_only=True)
    individual_children_names = serializers.SerializerMethodField()

    class Meta:
        model = Lesson
        fields = [
            "id",
            "group",
            "group_name",
            "direction_id",
            "direction_color",
            "is_individual",
            "individual_children",
            "individual_children_names",
            "schedule_slot",
            "room",
            "room_name",
            "teacher",
            "teacher_name",
            "starts_at",
            "ends_at",
            "starts_at_local",
            "ends_at_local",
            "status",
            "status_display",
            "rescheduled_from",
            "rescheduled_to_id",
            "is_modified",
            "cancel_reason_category",
            "cancel_reason_category_display",
            "cancel_reason",
            "note",
            "capacity",
            "enrolled_count",
            "has_conflict",
            "conflicting_lesson_ids",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            # Тот же принцип, что у RoomSerializer.branch/DirectionSerializer.branches
            # — привязать можно только ребёнка своей организации.
            self.fields["individual_children"].child_relation.queryset = Child.objects.for_tenant(
                request.user.organization
            )

    def get_group_name(self, obj):
        return obj.group.name if obj.group else None

    def get_direction_id(self, obj):
        return obj.group.direction_id if obj.group else None

    def get_direction_color(self, obj):
        return obj.group.direction.color if obj.group else None

    def get_room_name(self, obj):
        return obj.room.name if obj.room else None

    def get_teacher_name(self, obj):
        return obj.teacher.full_name if obj.teacher else None

    def get_capacity(self, obj):
        return obj.group.capacity if obj.group else None

    def get_individual_children_names(self, obj):
        if obj.group_id:
            return []
        # LessonViewSet.get_queryset прогревает prefetch_related
        # "individual_children" — без доп. запроса на занятие.
        return [child.full_name for child in obj.individual_children.all()]

    def get_enrolled_count(self, obj):
        if not obj.group:
            return None
        # В LessonViewSet.get_queryset группа приходит с annotate(enrolled_count=...)
        # (без доп. запроса на занятие). Но найденные conflicts.find_conflicting_lessons
        # для карточки предупреждения об конфликте (TRU-46) — обычный queryset без
        # этой аннотации; там считаем явно — это редкий путь (диалог подтверждения
        # на 1-2 занятия), не список календаря, лишний запрос тут не критичен.
        if hasattr(obj.group, "enrolled_count"):
            return obj.group.enrolled_count
        return obj.group.memberships.filter(left_at__isnull=True).count()

    def get_starts_at_local(self, obj):
        org = self.context["request"].organization
        tz = timezone.zoneinfo.ZoneInfo(org.timezone or "Asia/Almaty")
        return obj.starts_at.astimezone(tz).isoformat()

    def get_ends_at_local(self, obj):
        org = self.context["request"].organization
        tz = timezone.zoneinfo.ZoneInfo(org.timezone or "Asia/Almaty")
        return obj.ends_at.astimezone(tz).isoformat()

    def get_rescheduled_to_id(self, obj):
        try:
            return str(obj.rescheduled_to.id)
        except Lesson.DoesNotExist:
            return None

    def _conflicting_ids(self, obj):
        # "conflict_map" — предпосчитанный LessonViewSet.list/conflicts на
        # уже загруженном окне занятий (без доп. запросов, см. conflicts.py).
        # Если его нет в контексте (retrieve/create/update одного занятия) —
        # считаем сами одним индексированным запросом.
        if "conflict_map" in self.context:
            return self.context["conflict_map"].get(obj.id, set())
        if obj.status in (Lesson.Status.CANCELLED, Lesson.Status.RESCHEDULED):
            return set()
        conflicts = find_conflicting_lessons(
            obj.organization,
            starts_at=obj.starts_at,
            ends_at=obj.ends_at,
            room=obj.room,
            teacher=obj.teacher,
            exclude_id=obj.id,
        )
        return set(conflicts.values_list("id", flat=True))

    def get_has_conflict(self, obj):
        return bool(self._conflicting_ids(obj))

    def get_conflicting_lesson_ids(self, obj):
        return [str(i) for i in self._conflicting_ids(obj)]

    def validate(self, attrs):
        if attrs.get("ends_at") and attrs.get("starts_at"):
            if attrs["ends_at"] <= attrs["starts_at"]:
                raise serializers.ValidationError(
                    {"ends_at": "Конец занятия должен быть позже начала."}
                )

        # TRU-47: группа и individual_children взаимоисключающие источники
        # участников — либо групповое (участники из Group.memberships),
        # либо индивидуальное (участники — сам individual_children).
        # partial=True (PATCH) может не трогать ни то, ни другое — тогда
        # берём текущее значение с инстанса, а не считаем, что оно пустое.
        if "group" in attrs:
            group = attrs["group"]
        else:
            group = getattr(self.instance, "group", None) if self.instance else None

        if "individual_children" in attrs:
            individual_children = attrs["individual_children"]
        else:
            individual_children = (
                list(self.instance.individual_children.all()) if self.instance else []
            )

        if group and individual_children:
            raise serializers.ValidationError(
                {
                    "individual_children": "У группового занятия участники берутся из группы — "
                    "нельзя одновременно указать группу и детей напрямую."
                }
            )
        if not group and not individual_children:
            raise serializers.ValidationError(
                {
                    "individual_children": "Индивидуальное занятие (без группы) должно быть "
                    "привязано хотя бы к одному ребёнку."
                }
            )
        return attrs


class LessonEnrollmentSerializer(serializers.ModelSerializer):
    """Ответ на запись/список записей «поверх» группы (TRU-53)."""

    child_name = serializers.CharField(source="child.full_name", read_only=True)
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    enrolled_by_name = serializers.CharField(
        source="enrolled_by.full_name", read_only=True, default=None
    )

    class Meta:
        model = LessonEnrollment
        fields = [
            "id",
            "lesson",
            "child",
            "child_name",
            "kind",
            "kind_display",
            "enrolled_by",
            "enrolled_by_name",
            "cancelled_at",
            "created_at",
        ]
        read_only_fields = ["id", "enrolled_by", "cancelled_at", "created_at"]


class LessonEnrollSerializer(serializers.Serializer):
    """Вход для LessonService.enroll() — сам вызов сервиса делает view
    (нужен доступ к organization из request и обработка EnrollResult),
    здесь только валидация и скоуп по организации."""

    lesson = serializers.PrimaryKeyRelatedField(queryset=Lesson.objects.none())
    child = serializers.PrimaryKeyRelatedField(queryset=Child.objects.none())
    kind = serializers.ChoiceField(choices=LessonEnrollment.Kind.choices)
    confirm_capacity = serializers.BooleanField(required=False, default=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            org = request.organization
            self.fields["lesson"].queryset = Lesson.objects.for_tenant(org)
            self.fields["child"].queryset = Child.objects.for_tenant(org)
