from rest_framework import serializers

from .models import Subscription, SubscriptionFreeze, SubscriptionLedgerEntry
from .statuses import DISPLAY_LABELS, get_display_status


class SubscriptionSerializer(serializers.ModelSerializer):
    subscription_type_name = serializers.CharField(
        source="subscription_type_version.name", read_only=True
    )
    direction_name = serializers.CharField(source="direction.name", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    # «Заканчивается» — не статус в базе, а расчёт (TRU-62); тот же, что у
    # фильтра списка детей и экрана «Продления».
    display_status = serializers.SerializerMethodField()
    display_status_label = serializers.SerializerMethodField()

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
            "display_status",
            "display_status_label",
            "sessions_remaining_cache",
            "list_price",
            "discount_amount",
            "discount_reason",
            "price",
            "renewed_from",
        ]

    def get_display_status(self, obj):
        return get_display_status(obj)

    def get_display_status_label(self, obj):
        return DISPLAY_LABELS[get_display_status(obj)]


class SubscriptionLedgerEntrySerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = SubscriptionLedgerEntry
        fields = ["id", "kind", "kind_display", "delta", "comment", "created_at"]


class SubscriptionFreezeSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionFreeze
        fields = ["id", "starts_on", "ends_on", "reason"]
