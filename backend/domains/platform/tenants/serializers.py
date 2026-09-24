from rest_framework import serializers

from .models import Branch, Direction, Organization, Room


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = [
            "id",
            "name",
            "slug",
            "plan",
            "subscription_status",
            "is_active",
            "timezone",
            "settings",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class BranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = [
            "id",
            "organization",
            "name",
            "address",
            "phone",
            "working_hours",
            "created_at",
            "updated_at",
        ]
        # organization выставляется во view из request.user, а не из тела
        # запроса — иначе клиент мог бы привязать филиал к чужой организации.
        read_only_fields = ["id", "organization", "created_at", "updated_at"]


class RoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Room
        fields = ["id", "branch", "name", "capacity", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            # branch должен быть выбираем только среди филиалов той же
            # организации — иначе можно было бы создать зал в чужом филиале.
            self.fields["branch"].queryset = Branch.objects.for_tenant(request.user.organization)


class DirectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Direction
        fields = ["id", "name", "color", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]
