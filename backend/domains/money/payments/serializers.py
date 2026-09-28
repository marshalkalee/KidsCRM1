from rest_framework import serializers

from domains.money.subscriptions.models import Subscription

from .models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = [
            "id",
            "subscription",
            "amount",
            "method",
            "provider",
            "provider_transaction_id",
            "status",
            "confirmed_at",
            "received_by",
            "comment",
            "paid_at",
            "cancelled_reason",
            "deleted_at",
        ]
        read_only_fields = [
            "id",
            "provider",
            "provider_transaction_id",
            "status",
            "confirmed_at",
            "received_by",
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
