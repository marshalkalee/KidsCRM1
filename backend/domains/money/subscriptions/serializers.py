from rest_framework import serializers

from domains.money.payments.models import Payment

from .debt import subscription_debt
from .models import Subscription, SubscriptionFreeze, SubscriptionLedgerEntry, SubscriptionType
from .statuses import DISPLAY_LABELS, get_display_status


class SubscriptionFreezeSerializer(serializers.ModelSerializer):
    days = serializers.SerializerMethodField()

    class Meta:
        model = SubscriptionFreeze
        fields = ["id", "starts_on", "ends_on", "reason", "days"]

    def get_days(self, obj):
        return (obj.ends_on - obj.starts_on).days if obj.ends_on else None


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
    # История заморозок — в карточке ребёнка (TRU-63), без отдельного запроса.
    freezes = SubscriptionFreezeSerializer(many=True, read_only=True)
    # Долг по этому абонементу — сумма по умолчанию в «Принять оплату» (TRU-67).
    debt = serializers.SerializerMethodField()

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
            "debt",
            "renewed_from",
            "freezes",
        ]

    def get_debt(self, obj):
        return str(subscription_debt(obj))

    def get_display_status(self, obj):
        return get_display_status(obj)

    def get_display_status_label(self, obj):
        return DISPLAY_LABELS[get_display_status(obj)]


class SubscriptionLedgerEntrySerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = SubscriptionLedgerEntry
        fields = ["id", "kind", "kind_display", "delta", "comment", "created_at"]


class FreezeRequestSerializer(serializers.Serializer):
    starts_on = serializers.DateField()
    ends_on = serializers.DateField()
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if attrs["ends_on"] <= attrs["starts_on"]:
            raise serializers.ValidationError(
                {"ends_on": ["Дата окончания должна быть позже даты начала."]}
            )
        return attrs


class UnfreezeRequestSerializer(serializers.Serializer):
    # Пусто — разморозить сегодня (досрочно): дни, что остались, вернутся.
    actual_end_date = serializers.DateField(required=False, allow_null=True)


class SaleRequestSerializer(serializers.Serializer):
    """Продажа и продление (TRU-69): даты и суммы — типами, ошибки — по полям."""

    subscription_type_id = serializers.UUIDField()
    starts_on = serializers.DateField()
    discount_amount = serializers.DecimalField(
        max_digits=12, decimal_places=0, min_value=0, required=False, default=0
    )
    discount_reason = serializers.ChoiceField(
        choices=Subscription.DiscountReason.choices, required=False, allow_blank=True, default=""
    )
    paid_amount = serializers.DecimalField(
        max_digits=12, decimal_places=0, min_value=0, required=False, default=0
    )
    payment_method = serializers.ChoiceField(
        choices=Payment.Method.choices, required=False, default=Payment.Method.KASPI_TRANSFER
    )


class SellRequestSerializer(SaleRequestSerializer):
    child_id = serializers.UUIDField()
    branch_id = serializers.UUIDField()
    direction_id = serializers.UUIDField()


class SubscriptionTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionType
        fields = [
            "id",
            "name",
            "price",
            "is_unlimited",
            "quota_sessions",
            "duration_days",
            "directions",
            "branches",
            "is_active",
            "is_public",
        ]
