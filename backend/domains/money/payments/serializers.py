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
            "received_by",
            "comment",
            "paid_at",
            "cancelled_reason",
            "deleted_at",
        ]
        read_only_fields = ["id", "received_by", "paid_at", "cancelled_reason", "deleted_at"]
