from django.utils import timezone
from rest_framework import serializers

from domains.people.clients.models import Child
from domains.platform.core.active_branch import allowed_branch_ids
from domains.platform.core.mixins import TenantCreateMixin
from domains.platform.users.models import User

from .absences import absence_map
from .conflicts import find_conflicting_lessons
from .models import Lesson, LessonEnrollment, StaffAbsence


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
    # TRU-182: преподаватель в этот день отсутствует — «нужна замена».
    teacher_absence = serializers.SerializerMethodField()

    # Поля для календаря — считаются из уже загруженных select_related/
    # prefetch_related объектов во view, доп. запросов не делают (см.
    # LessonViewSet.get_queryset).
    group_name = serializers.SerializerMethodField()
    direction_id = serializers.SerializerMethodField()
    direction_color = serializers.SerializerMethodField()
    room_name = serializers.SerializerMethodField()
    teacher_name = serializers.SerializerMethodField()
    original_teacher_name = serializers.SerializerMethodField()
    is_substitution = serializers.SerializerMethodField()
    capacity = serializers.SerializerMethodField()
    enrolled_count = serializers.SerializerMethodField()
    trial_count = serializers.SerializerMethodField()
    makeup_count = serializers.SerializerMethodField()
    total_participants_count = serializers.SerializerMethodField()
    additional_participants = serializers.SerializerMethodField()

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
            "original_teacher",
            "original_teacher_name",
            "is_substitution",
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
            "trial_count",
            "makeup_count",
            "total_participants_count",
            "additional_participants",
            "has_conflict",
            "conflicting_lesson_ids",
            "teacher_absence",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "original_teacher",
            "created_at",
            "updated_at",
        ]

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

    def get_original_teacher_name(self, obj):
        return obj.original_teacher.full_name if obj.original_teacher else None

    def get_is_substitution(self, obj):
        return obj.original_teacher_id is not None

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

    def _active_enrollments(self, obj):
        if hasattr(obj, "active_enrollments"):
            return obj.active_enrollments
        if not hasattr(obj, "_serialized_active_enrollments"):
            obj._serialized_active_enrollments = list(
                obj.enrollments.filter(cancelled_at__isnull=True).select_related(
                    "child", "source_lead"
                )
            )
        return obj._serialized_active_enrollments

    def get_trial_count(self, obj):
        return sum(
            enrollment.kind == LessonEnrollment.Kind.TRIAL
            for enrollment in self._active_enrollments(obj)
        )

    def get_makeup_count(self, obj):
        return sum(
            enrollment.kind == LessonEnrollment.Kind.MAKEUP
            for enrollment in self._active_enrollments(obj)
        )

    def get_total_participants_count(self, obj):
        if obj.group_id:
            base_count = self.get_enrolled_count(obj)
        else:
            base_count = len(obj.individual_children.all())
        return base_count + len(self._active_enrollments(obj))

    def get_additional_participants(self, obj):
        return [
            {
                "enrollment_id": str(enrollment.id),
                "child_id": str(enrollment.child_id),
                "child_name": enrollment.child.full_name,
                "kind": enrollment.kind,
                "source_lead_id": (
                    str(enrollment.source_lead_id) if enrollment.source_lead_id else None
                ),
            }
            for enrollment in self._active_enrollments(obj)
        ]

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

    def get_teacher_absence(self, obj):
        # "absence_map" предпосчитан LessonViewSet.list на всё окно; для
        # одного занятия (retrieve/create/update) — один запрос.
        if "absence_map" in self.context:
            absence = self.context["absence_map"].get(obj.id)
        else:
            absence = absence_map(obj.organization, [obj]).get(obj.id)
        if absence is None:
            return None
        return {
            "id": str(absence.id),
            "kind": absence.kind,
            "kind_display": absence.get_kind_display(),
            "starts_on": absence.starts_on.isoformat(),
            "ends_on": absence.ends_on.isoformat(),
        }

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


class LessonSubstituteSerializer(serializers.Serializer):
    lesson_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False, max_length=500
    )
    teacher_id = serializers.UUIDField()
    notify_parents = serializers.BooleanField(default=True)

    def validate_lesson_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Занятия не должны повторяться.")
        return value


class LessonSubstitutionRemoveSerializer(serializers.Serializer):
    lesson_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False, max_length=500
    )

    def validate_lesson_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Занятия не должны повторяться.")
        return value


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
            "source_attendance",
            "source_lead",
            "enrolled_by",
            "enrolled_by_name",
            "cancelled_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "source_lead",
            "enrolled_by",
            "cancelled_at",
            "created_at",
        ]


class LessonEnrollSerializer(serializers.Serializer):
    """Вход для LessonService.enroll() — сам вызов сервиса делает view
    (нужен доступ к organization из request и обработка EnrollResult),
    здесь только валидация и скоуп по организации. source_attendance —
    только для kind=makeup (TRU-54): какой именно пропуск отрабатывается."""

    lesson = serializers.PrimaryKeyRelatedField(queryset=Lesson.objects.none())
    child = serializers.PrimaryKeyRelatedField(queryset=Child.objects.none())
    kind = serializers.ChoiceField(choices=LessonEnrollment.Kind.choices)
    confirm_capacity = serializers.BooleanField(required=False, default=False)
    source_attendance = serializers.PrimaryKeyRelatedField(
        queryset=Child.objects.none(), required=False, allow_null=True, default=None
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            from domains.scheduling.attendance.models import Attendance

            org = request.organization
            self.fields["lesson"].queryset = Lesson.objects.for_tenant(org)
            self.fields["child"].queryset = Child.objects.for_tenant(org)
            self.fields["source_attendance"].queryset = Attendance.objects.for_tenant(org)


class AvailableMakeupSerializer(serializers.Serializer):
    """TRU-54: строка в списке «доступных отработок» ребёнка — вход
    {"attendance": Attendance, "expires_on": date, "days_left": int}
    (см. enrollment_service.available_makeups_for_child)."""

    attendance_id = serializers.UUIDField(source="attendance.id")
    lesson = serializers.UUIDField(source="attendance.lesson.id")
    group_name = serializers.SerializerMethodField()
    room_name = serializers.SerializerMethodField()
    starts_at_local = serializers.SerializerMethodField()
    absence_reason_display = serializers.CharField(source="attendance.get_absence_reason_display")
    expires_on = serializers.DateField()
    days_left = serializers.IntegerField()

    def get_group_name(self, obj):
        group = obj["attendance"].lesson.group
        return group.name if group else None

    def get_room_name(self, obj):
        room = obj["attendance"].lesson.room
        return room.name if room else None

    def get_starts_at_local(self, obj):
        org = self.context["request"].organization
        tz = timezone.zoneinfo.ZoneInfo(org.timezone or "Asia/Almaty")
        return obj["attendance"].lesson.starts_at.astimezone(tz).isoformat()


class MakeupCandidateSerializer(serializers.ModelSerializer):
    """TRU-54: занятие-кандидат для отработки — с посчитанной вместимостью,
    чтобы фронт мог показать «мест нет» до попытки записи (сама запись всё
    равно пройдёт по подтверждению — см. LessonService.enroll)."""

    starts_at_local = serializers.SerializerMethodField()
    ends_at_local = serializers.SerializerMethodField()
    group_name = serializers.CharField(source="group.name", default=None)
    room_name = serializers.CharField(source="room.name", default=None)
    teacher_name = serializers.CharField(source="teacher.full_name", default=None)
    capacity = serializers.SerializerMethodField()
    current_count = serializers.SerializerMethodField()
    spots_left = serializers.SerializerMethodField()

    class Meta:
        model = Lesson
        fields = [
            "id",
            "group_name",
            "room_name",
            "teacher_name",
            "starts_at_local",
            "ends_at_local",
            "capacity",
            "current_count",
            "spots_left",
        ]

    def get_starts_at_local(self, obj):
        org = self.context["request"].organization
        tz = timezone.zoneinfo.ZoneInfo(org.timezone or "Asia/Almaty")
        return obj.starts_at.astimezone(tz).isoformat()

    def get_ends_at_local(self, obj):
        org = self.context["request"].organization
        tz = timezone.zoneinfo.ZoneInfo(org.timezone or "Asia/Almaty")
        return obj.ends_at.astimezone(tz).isoformat()

    def get_capacity(self, obj):
        return obj.group.capacity if obj.group_id else None

    def get_current_count(self, obj):
        return obj.participants().count()

    def get_spots_left(self, obj):
        if not obj.group_id:
            return None
        return obj.group.capacity - obj.participants().count()


class StaffAbsenceSerializer(serializers.ModelSerializer):
    staff_name = serializers.CharField(source="staff.full_name", read_only=True)
    staff_role = serializers.CharField(source="staff.role", read_only=True)
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    created_by_name = serializers.CharField(
        source="created_by.full_name", read_only=True, default=None
    )

    class Meta:
        model = StaffAbsence
        fields = [
            "id",
            "staff",
            "staff_name",
            "staff_role",
            "kind",
            "kind_display",
            "starts_on",
            "ends_on",
            "note",
            "created_by_name",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            self.fields["staff"].queryset = User.objects.filter(
                organization=request.user.organization, is_active=True
            )

    def validate(self, attrs):
        starts_on = attrs.get("starts_on", getattr(self.instance, "starts_on", None))
        ends_on = attrs.get("ends_on", getattr(self.instance, "ends_on", None))
        staff = attrs.get("staff", getattr(self.instance, "staff", None))
        if starts_on and ends_on and ends_on < starts_on:
            raise serializers.ValidationError({"ends_on": "Дата окончания раньше даты начала."})
        if ends_on and starts_on and (ends_on - starts_on).days > 366:
            raise serializers.ValidationError({"ends_on": "Отсутствие не может быть дольше года."})
        allowed = allowed_branch_ids(self.context["request"].user)
        if allowed is not None and staff is not None:
            # Д36: администратор филиала А не ведёт отсутствия сотрудника
            # только из филиала Б. Сотрудник без филиалов работает везде.
            staff_branches = set(staff.branches.values_list("id", flat=True))
            if staff_branches and not staff_branches & set(allowed):
                raise serializers.ValidationError({"staff": "Сотрудник работает в другом филиале."})
        overlap = StaffAbsence.objects.for_tenant(staff.organization).filter(
            staff=staff, starts_on__lte=ends_on, ends_on__gte=starts_on
        )
        if self.instance is not None:
            overlap = overlap.exclude(pk=self.instance.pk)
        first = overlap.first()
        if first is not None:
            raise serializers.ValidationError(
                {
                    "starts_on": (
                        f"На эти даты уже есть отсутствие: {first.get_kind_display().lower()} "
                        f"{first.starts_on:%d.%m}–{first.ends_on:%d.%m}."
                    )
                }
            )
        return attrs
