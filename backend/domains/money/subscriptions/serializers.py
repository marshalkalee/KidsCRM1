from rest_framework import serializers

from .models import Subscription, SubscriptionFreeze, SubscriptionLedgerEntry


class SubscriptionSerializer(serializers.ModelSerializer):
    subscription_type_name = serializers.CharField(
        source="subscription_type_version.name", read_only=True
    )
    direction_name = serializers.CharField(source="direction.name", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Subscription
        fields = [
            "id",
            "child",
            "subscription_type_name",
            "direction_name",
            "branch_name",
            "starts_on",
            "ends_on",
            "status",
            "status_display",
            "sessions_remaining_cache",
            "list_price",
            "discount_amount",
            "discount_reason",
            "price",
            "renewed_from",
        ]


class SubscriptionLedgerEntrySerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = SubscriptionLedgerEntry
        fields = ["id", "kind", "kind_display", "delta", "comment", "created_at"]


class SubscriptionFreezeSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionFreeze
        fields = ["id", "starts_on", "ends_on", "reason"]
