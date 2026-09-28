from rest_framework import serializers

from .models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    received_by_name = serializers.CharField(source="received_by.full_name", read_only=True)

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
            "received_by_name",
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
            "received_by_name",
            "paid_at",
            "cancelled_reason",
            "deleted_at",
        ]
