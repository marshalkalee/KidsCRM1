from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from domains.people.clients.models import Child
from domains.platform.core.text_validation import normalize_entity_name
from domains.platform.tenants.models import Room
from domains.platform.users.models import User

from . import queries
from .models import Group, GroupMembership


class GroupSerializer(serializers.ModelSerializer):
    teachers_count = serializers.IntegerField(read_only=True)
    members_count = serializers.IntegerField(read_only=True)
    # Для списка и карточки frontend2 (TRU-87) — без отдельных запросов за
    # справочниками.
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    direction_name = serializers.CharField(source="direction.name", read_only=True)
    direction_color = serializers.CharField(source="direction.color", read_only=True)
    teachers_detail = serializers.SerializerMethodField()
    fill_percent = serializers.SerializerMethodField()
    is_underfilled = serializers.SerializerMethodField()
    schedule = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = [
            "id",
            "name",
            "branch",
            "branch_name",
            "direction",
            "direction_name",
            "direction_color",
            "teachers",
            "teachers_detail",
            "capacity",
            "age_min",
            "age_max",
            "status",
            "is_public",
            "description",
            "trial_available",
            "trial_price",
            "exclude_from_ai_recommendations",
            "teachers_count",
            "members_count",
            "fill_percent",
            "is_underfilled",
            "schedule",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return
        organization = request.user.organization
        instance = self.instance if isinstance(self.instance, Group) else None
        # Только своя организация (раньше queryset был «все филиалы всех
        # организаций»). Архивные — только уже выбранные у этой группы (TRU-77).
        self.fields["branch"].queryset = queries.branch_choices(
            organization, instance.branch if instance else None
        )
        self.fields["direction"].queryset = queries.direction_choices(
            organization, instance.direction if instance else None
        )
        self.fields["teachers"].child_relation.queryset = queries.teacher_choices(organization)

    def validate(self, attrs):
        age_min = attrs.get("age_min", getattr(self.instance, "age_min", None))
        age_max = attrs.get("age_max", getattr(self.instance, "age_max", None))
        if age_min is not None and age_max is not None and age_min > age_max:
            raise serializers.ValidationError(
                {"age_min": _("Возраст «от» не может быть больше «до».")}
            )
        return attrs

    def validate_name(self, value):
        return normalize_entity_name(value)

    def validate_capacity(self, value):
        if not 1 <= value <= 100:
            raise serializers.ValidationError("Вместимость должна быть от 1 до 100.")
        return value

    def validate_age_min(self, value):
        if value is not None and value > 99:
            raise serializers.ValidationError("Возраст должен быть от 0 до 99 лет.")
        return value

    def validate_age_max(self, value):
        if value is not None and value > 99:
            raise serializers.ValidationError("Возраст должен быть от 0 до 99 лет.")
        return value

    def get_teachers_detail(self, group):
        return [{"id": str(t.id), "full_name": t.full_name} for t in group.teachers.all()]

    def _threshold(self):
        if "threshold" not in self.context:
            request = self.context.get("request")
            self.context["threshold"] = (
                queries.underfilled_threshold(request.user.organization) if request else 0
            )
        return self.context["threshold"]

    def get_fill_percent(self, group):
        return queries.fill_percent(group) if hasattr(group, "members_count") else None

    def get_is_underfilled(self, group):
        if not hasattr(group, "members_count"):
            return None
        return queries.is_underfilled(group, self._threshold())

    def get_schedule(self, group):
        # Только если слоты уже загружены (prefetch во вьюхе) — иначе пусто,
        # без запроса на каждую группу.
        cache = getattr(group, "_prefetched_objects_cache", {})
        if "schedule_templates" not in cache:
            return []
        template = queries.active_template(group)
        if template is None:
            return []
        return [
            {
                "weekday": slot.weekday,
                "start_time": slot.start_time.strftime("%H:%M"),
                "duration_minutes": slot.duration_minutes,
                "room": slot.room.name if slot.room else None,
                "teacher": slot.teacher.full_name if slot.teacher else None,
            }
            for slot in sorted(template.slots.all(), key=lambda s: (s.weekday, s.start_time))
        ]


class GroupMembershipSerializer(serializers.ModelSerializer):
    child_name = serializers.CharField(source="child.full_name", read_only=True)
    child_age = serializers.IntegerField(source="child.age", read_only=True)
    child_status = serializers.CharField(source="child.status", read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    joined_at = serializers.DateField(required=False)

    class Meta:
        model = GroupMembership
        fields = [
            "id",
            "group",
            "child",
            "child_name",
            "child_age",
            "child_status",
            "joined_at",
            "left_at",
            "note",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            # Иначе в группу можно было бы записать ребёнка чужой организации.
            organization = request.user.organization
            self.fields["child"].queryset = Child.objects.for_tenant(organization)
            self.fields["group"].queryset = Group.objects.for_tenant(organization)

    def validate(self, attrs):
        joined_at = attrs.setdefault("joined_at", timezone.localdate())
        if attrs.get("left_at") and attrs["left_at"] < joined_at:
            raise serializers.ValidationError(
                {"left_at": _("Дата выхода не может быть раньше даты вступления.")}
            )
        group, child = attrs.get("group"), attrs.get("child")
        if self.instance is None and group and child:
            # Не 500 от UniqueConstraint, а понятная ошибка.
            if GroupMembership.objects.filter(
                group=group, child=child, left_at__isnull=True
            ).exists():
                raise serializers.ValidationError({"child": _("Ребёнок уже в этой группе.")})
            if group.status != Group.Status.ACTIVE:
                raise serializers.ValidationError(
                    {"group": _("Группа не набирает — она приостановлена или закрыта.")}
                )
            members = GroupMembership.objects.filter(group=group, left_at__isnull=True).count()
            if members >= group.capacity:
                raise serializers.ValidationError(
                    {"group": _("В группе нет мест: %(n)s из %(n)s.") % {"n": group.capacity}}
                )
        return attrs

    def create(self, validated_data):
        validated_data["organization"] = validated_data["group"].organization
        return super().create(validated_data)


class GroupScheduleSlotSerializer(serializers.Serializer):
    """Один повторяющийся слот недельного расписания группы."""

    id = serializers.UUIDField(required=False)
    weekday = serializers.IntegerField(min_value=0, max_value=6)
    start_time = serializers.TimeField(input_formats=["%H:%M", "%H:%M:%S"])
    duration_minutes = serializers.IntegerField(min_value=15, max_value=360)
    room = serializers.PrimaryKeyRelatedField(
        queryset=Room.objects.none(), required=False, allow_null=True
    )
    teacher = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.none(), required=False, allow_null=True
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return
        organization = request.user.organization
        self.fields["room"].queryset = Room.objects.for_tenant(organization)
        self.fields["teacher"].queryset = User.objects.filter(
            organization=organization,
            role=User.Role.TEACHER,
            is_active=True,
        )

    def validate_room(self, room):
        group = self.context.get("group")
        if room is not None and group is not None and room.branch_id != group.branch_id:
            raise serializers.ValidationError(_("Зал должен относиться к филиалу группы."))
        return room


class GroupScheduleSerializer(serializers.Serializer):
    """Атомарная замена постоянного расписания и будущих занятий группы."""

    generate_weeks_ahead = serializers.IntegerField(min_value=1, max_value=12, default=8)
    slots = GroupScheduleSlotSerializer(many=True, max_length=21)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return
        child = self.fields["slots"].child
        child.fields["room"].queryset = Room.objects.for_tenant(request.user.organization)
        child.fields["teacher"].queryset = User.objects.filter(
            organization=request.user.organization,
            role=User.Role.TEACHER,
            is_active=True,
        )

    def validate_slots(self, slots):
        keys = [(slot["weekday"], slot["start_time"]) for slot in slots]
        if len(keys) != len(set(keys)):
            raise serializers.ValidationError(
                _("Нельзя добавить два занятия группы в один день и одно время.")
            )
        return slots
