from rest_framework import serializers

from .models import Branch, Direction, Organization, Room
from .working_hours import default_working_hours, normalize_working_hours


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = [
            "id",
            "name",
            "slug",
            "plan",
            "subscription_status",
            "is_active",
            "timezone",
            "settings",
            "created_at",
            "updated_at",
        ]
        # Тариф, статус подписки, slug и settings целиком клиенту не
        # доверяем: иначе владелец PATCH-ем сменил бы себе тариф или затёр
        # settings["onboarding"]. Название, часовой пояс и пороги
        # автостатусов меняются через organization/settings/ — тем же путём,
        # что веб (OrganizationSettingsForm).
        read_only_fields = [
            "id",
            "slug",
            "plan",
            "subscription_status",
            "is_active",
            "settings",
            "created_at",
            "updated_at",
        ]


class BranchSerializer(serializers.ModelSerializer):
    # Аннотация из BranchViewSet.get_queryset — для карточек филиалов в
    # настройках frontend2, без запроса залов на каждый филиал.
    rooms_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Branch
        fields = [
            "id",
            "organization",
            "name",
            "address",
            "phone",
            "working_hours",
            "is_active",
            "rooms_count",
            "created_at",
            "updated_at",
        ]
        # organization выставляется во view из request.user, а не из тела
        # запроса — иначе клиент мог бы привязать филиал к чужой организации.
        # is_active — намеренно НЕ read-only: архивирование филиала (веб-
        # экран "Настройки организации") — это PATCH is_active, а не DELETE
        # (тот делает soft-delete через deleted_at и убирает филиал из
        # for_tenant() совсем — архивный филиал должен там оставаться,
        # см. web_views.branch_archive).
        read_only_fields = ["id", "organization", "created_at", "updated_at"]

    def validate_working_hours(self, value):
        working_hours, errors = normalize_working_hours(value)
        if errors:
            raise serializers.ValidationError(errors)
        return working_hours

    def create(self, validated_data):
        # Как у веб-формы: без явного расписания — пн–пт 09:00–20:00.
        validated_data.setdefault("working_hours", default_working_hours())
        return super().create(validated_data)


class RoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Room
        fields = ["id", "branch", "name", "capacity", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            # branch должен быть выбираем только среди филиалов той же
            # организации — иначе можно было бы создать зал в чужом филиале.
            self.fields["branch"].queryset = Branch.objects.for_tenant(request.user.organization)


class DirectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Direction
        fields = [
            "id",
            "name",
            "color",
            "age_min",
            "age_max",
            "branches",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            # Направление можно отметить доступным только в активных
            # филиалах своей организации — тот же принцип, что и у
            # RoomSerializer.branch, плюс filter(is_active=True), как у
            # DirectionForm.__init__ в веб-версии. "branches" — M2M, DRF
            # оборачивает его в ManyRelatedField — queryset нужно менять у
            # child_relation, не у самого поля (иначе просто повисает
            # неиспользуемым атрибутом и фильтр не применяется).
            self.fields["branches"].child_relation.queryset = Branch.objects.for_tenant(
                request.user.organization
            ).filter(is_active=True)

    def validate(self, attrs):
        age_min = attrs.get("age_min")
        age_max = attrs.get("age_max")
        if age_min is not None and age_max is not None and age_max < age_min:
            raise serializers.ValidationError(
                {"age_max": "Возраст «до» не может быть меньше возраста «от»."}
            )
        return attrs
