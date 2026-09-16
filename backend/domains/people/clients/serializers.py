from django.utils import timezone
from rest_framework import serializers

from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number
from domains.platform.core.role_permissions import can_view_child_sensitive_fields, can_view_phone
from domains.platform.tenants.models import Direction

from .models import Child, ChildContact, ContactPhone, ParentContact


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


class ContactPhoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactPhone
        fields = ["id", "number", "phone_type"]
        read_only_fields = ["id"]

    def validate_number(self, value):
        try:
            return normalize_phone_number(value)
        except InvalidPhoneNumberError as exc:
            raise serializers.ValidationError(str(exc)) from exc


class ParentContactSerializer(serializers.ModelSerializer):
    # Не ModelSerializer-относительное поле, а вложенный список — телефоны
    # создаются/заменяются вместе с родителем одним запросом (см. create/update).
    phones = ContactPhoneSerializer(many=True)

    class Meta:
        model = ParentContact
        fields = [
            "id",
            "organization",
            "full_name",
            "phones",
            "whatsapp",
            "email",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "organization", "created_at", "updated_at"]

    def validate_whatsapp(self, value):
        if not value:
            return value
        try:
            return normalize_phone_number(value)
        except InvalidPhoneNumberError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def validate_phones(self, value):
        if not value:
            raise serializers.ValidationError("У родителя должен быть хотя бы один телефон.")
        return value

    def create(self, validated_data):
        phones_data = validated_data.pop("phones")
        parent_contact = ParentContact.objects.create(**validated_data)
        for phone_data in phones_data:
            ContactPhone.objects.create(parent_contact=parent_contact, **phone_data)
        return parent_contact

    def update(self, instance, validated_data):
        phones_data = validated_data.pop("phones", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if phones_data is not None:
            # По одной, а не queryset.delete(): bulk-delete на QuerySet идёт
            # мимо переопределённого Model.delete() и удалил бы физически,
            # а не мягко (SoftDeleteQuerySet его не переопределяет).
            for phone in instance.phones.all():
                phone.delete()
            for phone_data in phones_data:
                ContactPhone.objects.create(parent_contact=instance, **phone_data)
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        # Преподаватель не видит телефоны, если так настроено (RBAC, TRU-19).
        if request is not None and not can_view_phone(request.user):
            data.pop("phones", None)
            data.pop("whatsapp", None)
        return data


class ChildContactSerializer(serializers.ModelSerializer):
    parent_contact_full_name = serializers.CharField(
        source="parent_contact.full_name", read_only=True
    )

    class Meta:
        model = ChildContact
        fields = [
            "id",
            "child",
            "parent_contact",
            "parent_contact_full_name",
            "role",
            "is_payer",
            "is_primary_contact",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            org = request.user.organization
            # Иначе можно было бы привязать ребёнка/родителя чужой
            # организации — та же логика, что у ChildSerializer.directions.
            self.fields["child"].queryset = Child.objects.for_tenant(org)
            self.fields["parent_contact"].queryset = ParentContact.objects.for_tenant(org)

    def validate(self, attrs):
        # UniqueConstraint в модели страхует на уровне БД, но DRF не строит
        # из условного constraint автоматический валидатор — без этой
        # проверки повторная привязка упала бы IntegrityError (500), а не
        # чистой 400-ошибкой.
        child = attrs.get("child", getattr(self.instance, "child", None))
        parent_contact = attrs.get("parent_contact", getattr(self.instance, "parent_contact", None))
        if child and parent_contact:
            qs = ChildContact.objects.filter(child=child, parent_contact=parent_contact)
            if self.instance is not None:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError("Этот контакт уже привязан к этому ребёнку.")
        return attrs
