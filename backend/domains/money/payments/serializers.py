from rest_framework import serializers

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
