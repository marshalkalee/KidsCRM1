from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from domains.platform.tenants.models import Branch, Organization

User = get_user_model()


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
        read_only_fields = ["id", "organization", "created_at", "updated_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
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


class CustomTokenObtainSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["organization_id"] = str(user.organization_id) if user.organization_id else None
        token["role"] = user.role
        return token

    def validate(self, attrs):
        try:
            data = super().validate(attrs)
        except Exception as e:
            raise serializers.ValidationError({"detail": "Неверный телефон или пароль."}) from e
        return data


class OrganizationRegisterSerializer(serializers.Serializer):
    org_name = serializers.CharField(max_length=255)
    org_slug = serializers.SlugField(max_length=100)
    full_name = serializers.CharField(max_length=255)
    phone = serializers.CharField(max_length=20)
    password = serializers.CharField(write_only=True)

    def validate_org_slug(self, value):
        if Organization.objects.filter(slug=value).exists():
            raise serializers.ValidationError("Организация с таким slug уже существует.")
        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        org = Organization.objects.create(
            name=validated_data["org_name"],
            slug=validated_data["org_slug"],
        )
        user = User.objects.create_user(
            phone=validated_data["phone"],
            password=validated_data["password"],
            full_name=validated_data["full_name"],
            organization=org,
            role=User.Role.OWNER,
        )
        return org, user


class InviteStaffSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=255)
    phone = serializers.CharField(max_length=20)
    role = serializers.ChoiceField(choices=User.Role.choices)
    password = serializers.CharField(write_only=True)

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        organization = self.context["request"].organization
        user = User.objects.create_user(
            phone=validated_data["phone"],
            password=validated_data["password"],
            full_name=validated_data["full_name"],
            organization=organization,
            role=validated_data["role"],
        )
        return user


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Неверный текущий пароль.")
        return value

    def validate_new_password(self, value):
        validate_password(value)
        return value

    def save(self):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user
