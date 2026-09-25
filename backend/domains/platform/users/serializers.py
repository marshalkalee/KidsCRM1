import secrets

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils.text import slugify
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number
from domains.platform.tenants.models import Branch, Organization

User = get_user_model()


def check_role_change(actor, new_role, target=None):
    """Кто кому какую роль может дать (TRU-90). Сотрудников заводят владелец
    и управляющий (can_manage_staff — проверяет вьюха); здесь — то, что
    зависит от ролей: владельца назначает и меняет только владелец, свою
    роль не меняет никто (иначе управляющий повысил бы себя сам)."""
    only_owner = "{} может только владелец."
    if actor.role != User.Role.OWNER:
        if new_role == User.Role.OWNER:
            raise serializers.ValidationError({"role": only_owner.format("Назначить владельца")})
        if target is not None and target.role == User.Role.OWNER:
            raise serializers.ValidationError({"role": only_owner.format("Изменить владельца")})
    if target is not None and target.pk == actor.pk and new_role and new_role != target.role:
        raise serializers.ValidationError({"role": "Свою роль изменить нельзя."})


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

    def validate(self, attrs):
        request = self.context.get("request")
        if request is not None:
            role = attrs.get("role")
            if self.instance is not None:
                # Любая правка владельца (пароль, телефон) — только владельцем.
                check_role_change(request.user, role or self.instance.role, self.instance)
            else:
                check_role_change(request.user, role)
        return attrs

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


def unique_org_slug(name: str) -> str:
    # slug — технический идентификатор организации (в API), владелец его не
    # вводит: кириллица в slugify даёт пустую строку, поэтому суффикс всегда.
    base = slugify(name)[:80] or "center"
    return f"{base}-{secrets.token_hex(3)}"


class OrganizationRegisterSerializer(serializers.Serializer):
    org_name = serializers.CharField(max_length=255)
    # Необязателен: регистрация с сайта и из frontend2 его не спрашивает —
    # генерируется из названия (unique_org_slug).
    org_slug = serializers.SlugField(max_length=100, required=False)
    full_name = serializers.CharField(max_length=255)
    phone = serializers.CharField(max_length=20)
    password = serializers.CharField(write_only=True)

    def validate_org_slug(self, value):
        if Organization.objects.filter(slug=value).exists():
            raise serializers.ValidationError("Организация с таким slug уже существует.")
        return value

    def validate_phone(self, value):
        # Нормализованный номер — тот же формат, что у остальных телефонов
        # системы; иначе «8 701…» и «+7 701…» — два разных владельца.
        try:
            phone = normalize_phone_number(value)
        except InvalidPhoneNumberError as exc:
            raise serializers.ValidationError("Не похоже на номер телефона.") from exc
        # _base_manager — уникальность в базе действует и на удалённых
        # пользователей, иначе вместо ошибки формы — IntegrityError (500).
        if User._base_manager.filter(phone=phone).exists():
            raise serializers.ValidationError("Пользователь с таким телефоном уже есть.")
        return phone

    def validate_password(self, value):
        validate_password(value)
        return value

    @transaction.atomic
    def create(self, validated_data):
        # Атомарно: без этого сбой при создании владельца оставлял бы
        # организацию без единого пользователя.
        org = Organization.objects.create(
            name=validated_data["org_name"],
            slug=validated_data.get("org_slug") or unique_org_slug(validated_data["org_name"]),
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

    def validate(self, attrs):
        check_role_change(self.context["request"].user, attrs.get("role"))
        return attrs

    def create(self, validated_data):
        organization = self.context["request"].user.organization
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
