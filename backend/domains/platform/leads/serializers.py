from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers

from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number
from domains.platform.tenants.models import Branch, Direction
from domains.platform.users.models import User

from .models import Lead, LeadComment, LeadRejectionReason, LeadSource, LeadStatusChange
from .services import STALE_AFTER_DAYS


def _active_or_current(queryset, current):
    """Архивные значения справочника не выбрать заново, но уже стоящее у
    заявки сохраняется при правке других полей."""
    condition = Q(is_active=True)
    if current is not None:
        condition |= Q(pk=current.pk)
    return queryset.filter(condition)


class LeadSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True, default=None)
    direction_name = serializers.CharField(source="direction.name", read_only=True, default=None)
    source_name = serializers.CharField(source="source.name", read_only=True, default=None)
    assigned_to_name = serializers.CharField(
        source="assigned_to.full_name", read_only=True, default=None
    )
    rejection_reason_name = serializers.CharField(
        source="rejection_reason.name", read_only=True, default=None
    )
    converted_child_name = serializers.CharField(
        source="converted_child.full_name", read_only=True, default=None
    )
    days_in_status = serializers.SerializerMethodField()
    is_stale = serializers.SerializerMethodField()
    allowed_transitions = serializers.SerializerMethodField()

    class Meta:
        model = Lead
        fields = [
            "id",
            "parent_name",
            "phone",
            "child_name",
            "child_age",
            "branch",
            "branch_name",
            "direction",
            "direction_name",
            "source",
            "source_name",
            "assigned_to",
            "assigned_to_name",
            "status",
            "status_label",
            "status_changed_at",
            "days_in_status",
            "is_stale",
            "allowed_transitions",
            "rejection_reason",
            "rejection_reason_name",
            "rejection_comment",
            "converted_child",
            "converted_child_name",
            "created_at",
            "updated_at",
        ]
        # Статус и отказ меняются только через /status/ — там проверка
        # переходов, обязательная причина и запись в историю.
        read_only_fields = [
            "status",
            "status_changed_at",
            "rejection_reason",
            "rejection_comment",
            "converted_child",
            "created_at",
            "updated_at",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return
        organization = request.user.organization
        instance = self.instance if isinstance(self.instance, Lead) else None
        self.fields["branch"].queryset = _active_or_current(
            Branch.objects.for_tenant(organization), instance and instance.branch
        )
        self.fields["direction"].queryset = _active_or_current(
            Direction.objects.for_tenant(organization), instance and instance.direction
        )
        self.fields["source"].queryset = _active_or_current(
            LeadSource.objects.for_tenant(organization), instance and instance.source
        )
        self.fields["assigned_to"].queryset = User.objects.filter(
            organization=organization, is_active=True
        )

    def get_days_in_status(self, lead) -> int:
        # Не меньше нуля: доли секунды расхождения часов не должны давать «−1 день».
        return max(0, (timezone.now() - lead.status_changed_at).days)

    def get_allowed_transitions(self, lead) -> list[str]:
        """Куда можно перевести — карточка показывает только эти кнопки."""
        return [status for status in Lead.Status.values if lead.can_move_to(status)]

    def get_is_stale(self, lead) -> bool:
        limit = STALE_AFTER_DAYS.get(lead.status)
        return limit is not None and self.get_days_in_status(lead) >= limit

    def validate_phone(self, value):
        try:
            return normalize_phone_number(value)
        except InvalidPhoneNumberError as exc:
            raise serializers.ValidationError("Не похоже на номер телефона.") from exc

    def validate_child_age(self, value):
        if value is not None and value > 25:
            raise serializers.ValidationError("Проверьте возраст ребёнка.")
        return value


class LeadStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Lead.Status.choices)
    rejection_reason = serializers.PrimaryKeyRelatedField(
        queryset=LeadRejectionReason.objects.none(), required=False, allow_null=True
    )
    comment = serializers.CharField(required=False, allow_blank=True, default="")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            self.fields["rejection_reason"].queryset = LeadRejectionReason.objects.for_tenant(
                request.user.organization
            ).filter(is_active=True)


class LeadStatusChangeSerializer(serializers.ModelSerializer):
    from_status_label = serializers.SerializerMethodField()
    to_status_label = serializers.CharField(source="get_to_status_display", read_only=True)
    changed_by_name = serializers.CharField(
        source="changed_by.full_name", read_only=True, default=None
    )
    rejection_reason_name = serializers.CharField(
        source="rejection_reason.name", read_only=True, default=None
    )

    class Meta:
        model = LeadStatusChange
        fields = [
            "id",
            "from_status",
            "from_status_label",
            "to_status",
            "to_status_label",
            "changed_by",
            "changed_by_name",
            "changed_at",
            "rejection_reason",
            "rejection_reason_name",
            "comment",
        ]

    def get_from_status_label(self, change) -> str:
        return change.get_from_status_display() if change.from_status else ""


class LeadCommentSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.full_name", read_only=True, default=None)

    class Meta:
        model = LeadComment
        fields = ["id", "text", "author", "author_name", "created_at"]
        read_only_fields = ["author", "created_at"]


class LeadDictionarySerializer(serializers.ModelSerializer):
    """Источник или причина отказа. usage_count — сколько раз выбрано:
    по нему частые значения стоят в списке сверху."""

    usage_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        fields = ["id", "name", "is_active", "usage_count"]

    def validate_name(self, value):
        name = " ".join(value.split())
        if not name:
            raise serializers.ValidationError("Введите название.")
        organization = self.context["request"].user.organization
        duplicates = self.Meta.model.objects.for_tenant(organization).filter(name__iexact=name)
        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise serializers.ValidationError("Такое значение уже есть.")
        return name


class LeadSourceSerializer(LeadDictionarySerializer):
    class Meta(LeadDictionarySerializer.Meta):
        model = LeadSource


class LeadRejectionReasonSerializer(LeadDictionarySerializer):
    class Meta(LeadDictionarySerializer.Meta):
        model = LeadRejectionReason


class LeadBulkSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False, max_length=200)
    action = serializers.ChoiceField(choices=["status", "assign"])
    status = serializers.ChoiceField(choices=Lead.Status.choices, required=False)
    rejection_reason = serializers.PrimaryKeyRelatedField(
        queryset=LeadRejectionReason.objects.none(), required=False, allow_null=True
    )
    comment = serializers.CharField(required=False, allow_blank=True, default="")
    assigned_to = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.none(), required=False, allow_null=True
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            organization = request.user.organization
            self.fields["rejection_reason"].queryset = LeadRejectionReason.objects.for_tenant(
                organization
            ).filter(is_active=True)
            self.fields["assigned_to"].queryset = User.objects.filter(
                organization=organization, is_active=True
            )

    def validate(self, attrs):
        if attrs["action"] == "status":
            if not attrs.get("status"):
                raise serializers.ValidationError({"status": "Выберите статус."})
            # Массовый отказ — тоже только с причиной (критерий TRU-95).
            if attrs["status"] == Lead.Status.REJECTED and not attrs.get("rejection_reason"):
                raise serializers.ValidationError({"rejection_reason": "Укажите причину отказа."})
        elif "assigned_to" not in attrs:
            raise serializers.ValidationError({"assigned_to": "Выберите ответственного."})
        return attrs
