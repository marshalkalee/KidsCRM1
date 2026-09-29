from decimal import Decimal

from rest_framework import serializers

from .models import Subscription


class SubscriptionSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="subscription_type_version.name", read_only=True)
    is_unlimited = serializers.BooleanField(
        source="subscription_type_version.is_unlimited", read_only=True
    )
    quota_sessions = serializers.IntegerField(
        source="subscription_type_version.quota_sessions", read_only=True
    )
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    discount_reason_label = serializers.CharField(
        source="get_discount_reason_display", read_only=True
    )
    direction_name = serializers.CharField(source="direction.name", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True, allow_null=True)
    paid = serializers.SerializerMethodField()
    debt = serializers.SerializerMethodField()

    class Meta:
        model = Subscription
        fields = [
            "id",
            "child",
            "name",
            "status",
            "status_label",
            "direction",
            "direction_name",
            "branch",
            "branch_name",
            "starts_on",
            "ends_on",
            "is_unlimited",
            "quota_sessions",
            "sessions_remaining_cache",
            "list_price",
            "discount_amount",
            "discount_reason",
            "discount_reason_label",
            "discount_comment",
            "price",
            "paid",
            "debt",
            "created_at",
        ]
        read_only_fields = fields

    def get_paid(self, subscription):
        return str(getattr(subscription, "paid", Decimal("0")))

    def get_debt(self, subscription):
        paid = getattr(subscription, "paid", Decimal("0"))
        return str(max(Decimal("0"), subscription.price - paid))
