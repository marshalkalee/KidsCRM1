from urllib.parse import quote

from rest_framework import serializers

from domains.money.subscriptions.models import Subscription

from .models import Payment, PaymentRequest


class PaymentSerializer(serializers.ModelSerializer):
    received_by_name = serializers.CharField(source="received_by.full_name", read_only=True)
    payer_name = serializers.CharField(source="payer.full_name", read_only=True, default=None)
    method_display = serializers.CharField(source="get_method_display", read_only=True)
    idempotency_key = serializers.UUIDField(write_only=True, required=False)

    class Meta:
        model = Payment
        fields = [
            "id",
            "subscription",
            "amount",
            "method",
            "method_display",
            "idempotency_key",
            "provider",
            "provider_transaction_id",
            "status",
            "confirmed_at",
            "received_by",
            "received_by_name",
            "comment",
            "paid_at",
            "cancelled_reason",
            "deleted_at",
            "payer",
            "payer_name",
        ]
        read_only_fields = [
            "id",
            "provider",
            "provider_transaction_id",
            "status",
            "confirmed_at",
            "received_by",
            "received_by_name",
            "paid_at",
            "cancelled_reason",
            "deleted_at",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            # Иначе можно записать оплату на абонемент чужой организации:
            # queryset поля по умолчанию — абонементы всех центров.
            self.fields["subscription"].queryset = Subscription.objects.for_tenant(
                request.user.organization
            )

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Сумма оплаты должна быть больше нуля.")
        return value


class PaymentRequestSerializer(serializers.ModelSerializer):
    """Счёт на удалённую оплату Kaspi (payments/remote.py). На вход —
    абонемент, сумма, телефон (пусто — телефон плательщика) и ключ от
    двойного клика; остальное заполняет сервер."""

    idempotency_key = serializers.UUIDField(write_only=True, required=False)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    child = serializers.UUIDField(source="subscription.child_id", read_only=True)
    child_name = serializers.CharField(source="subscription.child.full_name", read_only=True)
    subscription_name = serializers.CharField(
        source="subscription.subscription_type_version.name", read_only=True
    )
    parent_name = serializers.CharField(
        source="parent_contact.full_name", read_only=True, default=""
    )
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    whatsapp_url = serializers.SerializerMethodField()

    class Meta:
        model = PaymentRequest
        fields = [
            "id",
            "subscription",
            "subscription_name",
            "child",
            "child_name",
            "parent_name",
            "phone",
            "amount",
            "idempotency_key",
            "channel",
            "status",
            "status_display",
            "message",
            "pay_url",
            "whatsapp_url",
            "expires_at",
            "paid_at",
            "cancelled_at",
            "created_at",
            "created_by_name",
            "payment",
        ]
        read_only_fields = [
            f for f in fields if f not in ("subscription", "amount", "phone", "idempotency_key")
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            self.fields["subscription"].queryset = Subscription.objects.for_tenant(
                request.user.organization
            )

    def get_whatsapp_url(self, obj):
        digits = "".join(ch for ch in obj.phone if ch.isdigit())
        if not digits:
            return ""
        return f"https://wa.me/{digits}?text={quote(obj.message)}"

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Сумма счёта должна быть больше нуля.")
        return value
