from rest_framework import serializers

from domains.money.subscriptions.models import Subscription

from .models import Payment


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
