from django.utils import timezone
from rest_framework import serializers

from domains.platform.core.role_permissions import can_view_child_sensitive_fields
from domains.platform.tenants.models import Direction

from .models import Child


class ChildSerializer(serializers.ModelSerializer):
    age = serializers.ReadOnlyField()

    class Meta:
        model = Child
        fields = [
            "id",
            "organization",
            "full_name",
            "birth_date",
            "age",
            "gender",
            "directions",
            "medical_notes",
            "photo_url",
            "status",
            "leave_reason",
            "consent_given",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "organization", "created_at", "updated_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            # Иначе ребёнка можно было бы привязать к направлению чужой
            # организации — та же логика, что у RoomSerializer.branch. M2M
            # оборачивается в ManyRelatedField — queryset у неё на
            # child_relation, а не на самом поле (в отличие от FK у Room).
            self.fields["directions"].child_relation.queryset = Direction.objects.for_tenant(
                request.user.organization
            )

    def validate_birth_date(self, value):
        if value > timezone.now().date():
            raise serializers.ValidationError("Дата рождения не может быть в будущем.")
        return value

    def validate(self, attrs):
        status = attrs.get("status", getattr(self.instance, "status", None))
        leave_reason = attrs.get("leave_reason", getattr(self.instance, "leave_reason", ""))
        if status == Child.Status.LEFT and not leave_reason.strip():
            raise serializers.ValidationError(
                {"leave_reason": "Причина ухода обязательна при переводе в «ушёл»."}
            )

        if self.instance is not None and "status" in attrs:
            previous = self.instance.status
            new = attrs["status"]
            if previous != new:
                allowed = Child.ALLOWED_STATUS_TRANSITIONS.get(previous, set())
                if new not in allowed:
                    raise serializers.ValidationError(
                        {"status": (f"Недопустимый переход статуса: {previous} → {new}.")}
                    )
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        # Преподаватель видит ребёнка, но не административные поля —
        # причина ухода и согласие на обработку данных не его дело (RBAC).
        if request is not None and not can_view_child_sensitive_fields(request.user):
            data.pop("leave_reason", None)
            data.pop("consent_given", None)
        return data
