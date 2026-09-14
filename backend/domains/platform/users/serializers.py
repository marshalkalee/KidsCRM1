from rest_framework import serializers

from domains.platform.tenants.models import Branch

from .models import User


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True, required=False, style={"input_type": "password"}
    )

    class Meta:
        model = User
        fields = [
            "id",
            "phone",
            "full_name",
            "role",
            "organization",
            "branches",
            "is_active",
            "created_at",
            "updated_at",
            "password",
        ]
        # organization выставляется во view из request.user, не из тела запроса
        # — иначе можно было бы привязать сотрудника к чужой организации.
        read_only_fields = ["id", "organization", "created_at", "updated_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            # Тот же принцип, что у Room.branch: филиалы для привязки —
            # только из своей организации. branches — ManyToMany, поэтому
            # DRF оборачивает поле в ManyRelatedField — queryset для
            # валидации лежит на child_relation, а не на самом поле.
            self.fields["branches"].child_relation.queryset = Branch.objects.for_tenant(
                request.user.organization
            )

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        user = super().create(validated_data)
        if password:
            user.set_password(password)
            user.save(update_fields=["password"])
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        user = super().update(instance, validated_data)
        if password:
            user.set_password(password)
            user.save(update_fields=["password"])
        return user
