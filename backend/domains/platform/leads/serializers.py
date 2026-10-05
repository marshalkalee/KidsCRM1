from decimal import Decimal

from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers

from domains.money.payments.models import Payment
from domains.money.subscriptions.models import Subscription
from domains.people.clients.models import Child, ChildContact
from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number
from domains.platform.core.text_validation import normalize_entity_name, normalize_person_name
from domains.platform.tenants.models import Branch, Direction
from domains.platform.users.models import User

from .campaigns import next_code, site_link, whatsapp_links
from .models import (
    Lead,
    LeadCampaign,
    LeadComment,
    LeadRejectionReason,
    LeadSource,
    LeadStage,
    LeadStatusChange,
)
from .services import STALE_AFTER_DAYS
from .stages import Funnel


def _funnel(context, obj) -> Funnel:
    """Этапы центра один раз на сериализацию (список, доска — сотни карточек)."""
    funnel = context.get("funnel")
    if funnel is None:
        funnel = context["funnel"] = Funnel(obj.organization)
    return funnel


def _active_or_current(queryset, current):
    """Архивные значения справочника не выбрать заново, но уже стоящее у
    заявки сохраняется при правке других полей."""
    condition = Q(is_active=True)
    if current is not None:
        condition |= Q(pk=current.pk)
    return queryset.filter(condition)


class LeadSerializer(serializers.ModelSerializer):
    # Названия — этапов центра (TRU-154): переименованный «Связались»
    # подписывается по-новому везде, где показан статус.
    status_label = serializers.SerializerMethodField()
    stage = serializers.SerializerMethodField()
    stage_name = serializers.SerializerMethodField()
    stage_color = serializers.SerializerMethodField()
    allowed_stages = serializers.SerializerMethodField()
    branch_name = serializers.CharField(source="branch.name", read_only=True, default=None)
    direction_name = serializers.CharField(source="direction.name", read_only=True, default=None)
    source_name = serializers.CharField(source="source.name", read_only=True, default=None)
    campaign_name = serializers.CharField(source="campaign.name", read_only=True, default=None)
    assigned_to_name = serializers.CharField(
        source="assigned_to.full_name", read_only=True, default=None
    )
    rejection_reason_name = serializers.CharField(
        source="rejection_reason.name", read_only=True, default=None
    )
    converted_child_name = serializers.CharField(
        source="converted_child.full_name", read_only=True, default=None
    )
    days_in_status = serializers.SerializerMethodField()
    is_stale = serializers.SerializerMethodField()
    allowed_transitions = serializers.SerializerMethodField()
    trial_booking = serializers.SerializerMethodField()
    sold_subscription_details = serializers.SerializerMethodField()

    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    renewal_child_name = serializers.CharField(
        source="child.full_name", read_only=True, default=None
    )

    class Meta:
        model = Lead
        fields = [
            "id",
            "kind",
            "kind_label",
            "child",
            "renewal_child_name",
            "parent_name",
            "phone",
            "child_name",
            "child_age",
            "branch",
            "branch_name",
            "direction",
            "direction_name",
            "source",
            "source_name",
            "campaign",
            "campaign_name",
            "assigned_to",
            "assigned_to_name",
            "status",
            "status_label",
            "stage",
            "stage_name",
            "stage_color",
            "status_changed_at",
            "days_in_status",
            "is_stale",
            "allowed_transitions",
            "allowed_stages",
            "trial_booking",
            "rejection_reason",
            "rejection_reason_name",
            "rejection_comment",
            "converted_child",
            "converted_child_name",
            "sold_subscription",
            "sold_subscription_details",
            "created_at",
            "updated_at",
        ]
        # Статус и отказ меняются только через /status/ — там проверка
        # переходов, обязательная причина и запись в историю.
        # Вид и клиент — только при создании продления через сервис (TRU-98);
        # в API создаются только новые заявки.
        read_only_fields = [
            "kind",
            "child",
            "status",
            "status_changed_at",
            "rejection_reason",
            "rejection_comment",
            "converted_child",
            "sold_subscription",
            "created_at",
            "updated_at",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return
        organization = request.user.organization
        instance = self.instance if isinstance(self.instance, Lead) else None
        self.fields["branch"].queryset = _active_or_current(
            Branch.objects.for_tenant(organization), instance and instance.branch
        )
        self.fields["direction"].queryset = _active_or_current(
            Direction.objects.for_tenant(organization), instance and instance.direction
        )
        self.fields["source"].queryset = _active_or_current(
            LeadSource.objects.for_tenant(organization), instance and instance.source
        )
        self.fields["campaign"].queryset = _active_or_current(
            LeadCampaign.objects.for_tenant(organization), instance and instance.campaign
        )
        self.fields["assigned_to"].queryset = User.objects.filter(
            organization=organization, is_active=True
        )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        # Публикация живёт внутри источника (TRU-165): без источника он
        # берётся из публикации, другой источник — ошибка, а не тихая правка.
        campaign = attrs.get("campaign", getattr(self.instance, "campaign", None))
        if campaign is not None:
            source = attrs.get("source", getattr(self.instance, "source", None))
            if source is None:
                attrs["source"] = campaign.source
            elif source.pk != campaign.source_id:
                raise serializers.ValidationError(
                    {"campaign": f"Публикация из источника «{campaign.source.name}»."}
                )
        return attrs

    def _stage(self, lead) -> LeadStage:
        return _funnel(self.context, lead).of(lead)

    def get_status_label(self, lead) -> str:
        return _funnel(self.context, lead).label(lead.status)

    def get_stage(self, lead) -> str:
        return str(self._stage(lead).pk)

    def get_stage_name(self, lead) -> str:
        return self._stage(lead).name

    def get_stage_color(self, lead) -> str:
        return self._stage(lead).color

    def get_allowed_stages(self, lead) -> list[str]:
        """Этапы, на которые можно перенести, — кнопки в карточке заявки."""
        funnel = _funnel(self.context, lead)
        return funnel.transitions(lead.kind).get(str(funnel.of(lead).pk), [])

    def get_days_in_status(self, lead) -> int:
        # Не меньше нуля: доли секунды расхождения часов не должны давать «−1 день».
        return max(0, (timezone.now() - lead.status_changed_at).days)

    def get_allowed_transitions(self, lead) -> list[str]:
        """Куда можно перевести — карточка показывает только эти кнопки."""
        return [status for status in Lead.statuses_for(lead.kind) if lead.can_move_to(status)]

    def get_is_stale(self, lead) -> bool:
        limit = STALE_AFTER_DAYS.get(lead.status)
        return limit is not None and self.get_days_in_status(lead) >= limit

    def get_trial_booking(self, lead):
        view = self.context.get("view")
        if view is not None and view.action in ("list", "board", "export"):
            return None
        enrollment = (
            lead.trial_enrollments.filter(cancelled_at__isnull=True)
            .select_related(
                "child",
                "lesson__group__branch",
                "lesson__group__direction",
                "lesson__room",
                "lesson__teacher",
            )
            .first()
        )
        if enrollment is None:
            return None
        lesson = enrollment.lesson
        tz = timezone.zoneinfo.ZoneInfo(lead.organization.timezone or "Asia/Almaty")
        return {
            "enrollment_id": str(enrollment.id),
            "lesson_id": str(lesson.id),
            "child_id": str(enrollment.child_id),
            "child_name": enrollment.child.full_name,
            "starts_at_local": lesson.starts_at.astimezone(tz).isoformat(),
            "ends_at_local": lesson.ends_at.astimezone(tz).isoformat(),
            "group_name": lesson.group.name,
            "branch_name": lesson.group.branch.name,
            "direction_name": lesson.group.direction.name,
            "room_name": lesson.room.name if lesson.room else None,
            "teacher_name": lesson.teacher.full_name if lesson.teacher else None,
        }

    def get_sold_subscription_details(self, lead):
        subscription = lead.sold_subscription
        if subscription is None:
            return None
        return {
            "id": str(subscription.id),
            "name": subscription.subscription_type_version.name,
            "starts_on": subscription.starts_on,
            "ends_on": subscription.ends_on,
            "status": subscription.status,
            "price": str(subscription.price),
            "sessions_remaining": subscription.sessions_remaining_cache,
        }

    def validate_phone(self, value):
        try:
            return normalize_phone_number(value)
        except InvalidPhoneNumberError as exc:
            raise serializers.ValidationError("Не похоже на номер телефона.") from exc

    def validate_parent_name(self, value):
        return normalize_person_name(value)

    def validate_child_name(self, value):
        return normalize_person_name(value) if value else value

    def validate_child_age(self, value):
        if value is not None and not 1 <= value <= 25:
            raise serializers.ValidationError("Проверьте возраст ребёнка.")
        return value


class LeadStatusSerializer(serializers.Serializer):
    # Этап центра (TRU-154) или, как раньше, роль — тогда системный этап.
    status = serializers.ChoiceField(choices=Lead.Status.choices, required=False)
    stage = serializers.PrimaryKeyRelatedField(queryset=LeadStage.objects.none(), required=False)
    rejection_reason = serializers.PrimaryKeyRelatedField(
        queryset=LeadRejectionReason.objects.none(), required=False, allow_null=True
    )
    comment = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            self.fields["rejection_reason"].queryset = LeadRejectionReason.objects.for_tenant(
                request.user.organization
            ).filter(is_active=True)
            self.fields["stage"].queryset = LeadStage.objects.for_tenant(request.user.organization)

    def validate(self, attrs):
        if not attrs.get("status") and not attrs.get("stage"):
            raise serializers.ValidationError({"status": "Выберите этап."})
        return attrs


class TrialBookingSerializer(serializers.Serializer):
    lesson = serializers.UUIDField()


class TrialBookingCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, trim_whitespace=True)


class LeadConversionQuerySerializer(serializers.Serializer):
    child_name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    birth_date = serializers.DateField(required=False)

    def validate_child_name(self, value):
        return normalize_person_name(value) if value else value


class LeadConversionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["create_new", "existing_parent", "existing_child"])
    child_id = serializers.UUIDField(required=False)
    parent_id = serializers.UUIDField(required=False)
    child_name = serializers.CharField(max_length=255)
    birth_date = serializers.DateField()
    gender = serializers.ChoiceField(choices=Child.Gender.choices)
    parent_name = serializers.CharField(max_length=255)
    link_role = serializers.ChoiceField(
        choices=ChildContact.Role.choices, default=ChildContact.Role.MOTHER
    )
    consent_given = serializers.BooleanField()

    def validate_child_name(self, value):
        value = normalize_person_name(value)
        if len(value.split()) < 2:
            raise serializers.ValidationError("Укажите фамилию и имя ребёнка.")
        return value

    def validate_parent_name(self, value):
        value = normalize_person_name(value)
        if len(value.split()) < 2:
            raise serializers.ValidationError("Укажите фамилию и имя родителя.")
        return value

    def validate_birth_date(self, value):
        if value > timezone.localdate():
            raise serializers.ValidationError("Дата рождения не может быть в будущем.")
        return value

    def validate_consent_given(self, value):
        if not value:
            raise serializers.ValidationError(
                "Подтвердите согласие на обработку персональных данных."
            )
        return value

    def validate(self, attrs):
        if attrs["decision"] == "existing_child" and not attrs.get("child_id"):
            raise serializers.ValidationError({"child_id": "Выберите ребёнка."})
        if attrs["decision"] == "existing_parent" and not attrs.get("parent_id"):
            raise serializers.ValidationError({"parent_id": "Выберите родителя."})
        return attrs


class LeadSaleSerializer(serializers.Serializer):
    subscription_type = serializers.UUIDField()
    starts_on = serializers.DateField()
    discount_amount = serializers.DecimalField(
        max_digits=12, decimal_places=0, min_value=Decimal("0"), default=Decimal("0")
    )
    discount_reason = serializers.ChoiceField(
        choices=Subscription.DiscountReason.choices,
        required=False,
        allow_blank=True,
        default="",
    )
    discount_comment = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=255
    )
    paid_amount = serializers.DecimalField(max_digits=12, decimal_places=0, min_value=Decimal("0"))
    payment_method = serializers.ChoiceField(choices=Payment.Method.choices)
    comment = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    group = serializers.UUIDField(required=False, allow_null=True)

    def validate_starts_on(self, value):
        if value < timezone.localdate():
            raise serializers.ValidationError("Дата начала не может быть в прошлом.")
        return value

    def validate(self, attrs):
        if attrs["discount_amount"] and not attrs.get("discount_reason"):
            raise serializers.ValidationError(
                {"discount_reason": "Для скидки обязательно укажите причину."}
            )
        return attrs


class TrialLessonSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    starts_at_local = serializers.SerializerMethodField()
    ends_at_local = serializers.SerializerMethodField()
    group_name = serializers.CharField(source="group.name")
    branch_name = serializers.CharField(source="group.branch.name")
    direction_name = serializers.CharField(source="group.direction.name")
    room_name = serializers.CharField(source="room.name", allow_null=True)
    teacher_name = serializers.CharField(source="teacher.full_name", allow_null=True)
    age_min = serializers.IntegerField(source="group.age_min", allow_null=True)
    age_max = serializers.IntegerField(source="group.age_max", allow_null=True)
    capacity = serializers.IntegerField(source="group.capacity")
    occupied_count = serializers.IntegerField()
    spots_left = serializers.SerializerMethodField()

    def _local(self, value):
        organization = self.context["request"].user.organization
        tz = timezone.zoneinfo.ZoneInfo(organization.timezone or "Asia/Almaty")
        return value.astimezone(tz).isoformat()

    def get_starts_at_local(self, lesson):
        return self._local(lesson.starts_at)

    def get_ends_at_local(self, lesson):
        return self._local(lesson.ends_at)

    def get_spots_left(self, lesson):
        return lesson.group.capacity - lesson.occupied_count


class LeadStatusChangeSerializer(serializers.ModelSerializer):
    from_status_label = serializers.SerializerMethodField()
    # По ссылке на этап (TRU-154): после переименования история читается
    # новым названием, а свой этап виден своим, а не названием роли.
    to_status_label = serializers.SerializerMethodField()
    to_stage_color = serializers.SerializerMethodField()
    changed_by_name = serializers.CharField(
        source="changed_by.full_name", read_only=True, default=None
    )
    rejection_reason_name = serializers.CharField(
        source="rejection_reason.name", read_only=True, default=None
    )

    class Meta:
        model = LeadStatusChange
        fields = [
            "id",
            "event_type",
            "from_status",
            "from_status_label",
            "to_status",
            "to_status_label",
            "to_stage_color",
            "changed_by",
            "changed_by_name",
            "changed_at",
            "is_automatic",
            "rejection_reason",
            "rejection_reason_name",
            "comment",
        ]

    def get_from_status_label(self, change) -> str:
        if not change.from_status:
            return ""
        return _funnel(self.context, change).label(change.from_status)

    def get_to_status_label(self, change) -> str:
        return _funnel(self.context, change).for_change(change).name

    def get_to_stage_color(self, change) -> str:
        return _funnel(self.context, change).for_change(change).color


class LeadStageSerializer(serializers.ModelSerializer):
    """Этап воронки центра (TRU-154). Системный этап: роль не меняется и
    не скрывается; свой — только внутри ролей «в работе»."""

    role_label = serializers.CharField(source="get_role_display", read_only=True)
    lead_count = serializers.SerializerMethodField()

    class Meta:
        model = LeadStage
        fields = [
            "id",
            "name",
            "role",
            "role_label",
            "is_system",
            "order",
            "color",
            "is_hidden",
            "lead_count",
        ]
        read_only_fields = ["is_system", "order"]

    def get_lead_count(self, stage) -> int:
        counts = self.context.get("lead_counts", {})
        return counts.get((stage.role, None if stage.is_system else stage.pk), 0)

    def validate_name(self, value):
        name = " ".join(value.split())
        if not name:
            raise serializers.ValidationError("Введите название этапа.")
        request = self.context["request"]
        clash = LeadStage.objects.for_tenant(request.user.organization).filter(name__iexact=name)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("Этап с таким названием уже есть.")
        return name

    def validate(self, attrs):
        stage = self.instance
        if stage is not None and stage.is_system:
            if "role" in attrs and attrs["role"] != stage.role:
                raise serializers.ValidationError(
                    {"role": "У основного этапа роль не меняется — на ней держится воронка."}
                )
            if attrs.get("is_hidden"):
                raise serializers.ValidationError(
                    {"is_hidden": "Основной этап нельзя скрыть — его можно переименовать."}
                )
        elif "role" in attrs or stage is None:
            role = attrs.get("role", stage.role if stage else None)
            if role not in LeadStage.CUSTOM_ROLES:
                raise serializers.ValidationError(
                    {"role": "Свой этап можно добавить только в работу с заявкой, не в исход."}
                )
            if stage is not None and role != stage.role and stage.leads.exists():
                raise serializers.ValidationError(
                    {"role": "На этапе есть заявки — сначала перенесите их."}
                )
        return attrs


class LeadCommentSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.full_name", read_only=True, default=None)

    class Meta:
        model = LeadComment
        fields = ["id", "text", "author", "author_name", "created_at"]
        read_only_fields = ["author", "created_at"]

    def validate_text(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Введите комментарий.")
        if len(value) > 2000:
            raise serializers.ValidationError("Введите не более 2000 символов.")
        return value


class LeadDictionarySerializer(serializers.ModelSerializer):  # noqa: D101
    """Источник или причина отказа. usage_count — сколько раз выбрано:
    по нему частые значения стоят в списке сверху."""

    usage_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        fields = ["id", "name", "is_active", "usage_count"]

    def validate_name(self, value):
        name = normalize_entity_name(value, max_length=100)
        organization = self.context["request"].user.organization
        duplicates = self.Meta.model.objects.for_tenant(organization).filter(name__iexact=name)
        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise serializers.ValidationError("Такое значение уже есть.")
        return name


class LeadCampaignSerializer(LeadDictionarySerializer):
    """Публикация (TRU-165): код выдаётся при создании и не меняется — он
    уже стоит в ссылках под роликами."""

    source_name = serializers.CharField(source="source.name", read_only=True)
    whatsapp_links = serializers.SerializerMethodField()
    site_link = serializers.SerializerMethodField()

    class Meta(LeadDictionarySerializer.Meta):
        model = LeadCampaign
        fields = [
            *LeadDictionarySerializer.Meta.fields,
            "source",
            "source_name",
            "code",
            "whatsapp_links",
            "site_link",
        ]
        read_only_fields = ["code"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            self.fields["source"].queryset = LeadSource.objects.for_tenant(
                request.user.organization
            )

    def get_whatsapp_links(self, campaign) -> list[dict]:
        return whatsapp_links(campaign)

    def get_site_link(self, campaign) -> str | None:
        return site_link(campaign)

    def create(self, validated_data):
        validated_data["code"] = next_code(validated_data["organization"])
        return super().create(validated_data)


class LeadSourceSerializer(LeadDictionarySerializer):
    class Meta(LeadDictionarySerializer.Meta):
        model = LeadSource


class LeadRejectionReasonSerializer(LeadDictionarySerializer):
    class Meta(LeadDictionarySerializer.Meta):
        model = LeadRejectionReason
        fields = [*LeadDictionarySerializer.Meta.fields, "kind"]

    def validate(self, attrs):
        # Дубль проверяем внутри своего вида: «Дорого» есть и у новых, и у продлений.
        return attrs

    def validate_name(self, value):
        name = normalize_entity_name(value, max_length=100)
        kind = self.initial_data.get("kind") or (self.instance.kind if self.instance else "new")
        organization = self.context["request"].user.organization
        duplicates = LeadRejectionReason.objects.for_tenant(organization).filter(
            name__iexact=name, kind=kind
        )
        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise serializers.ValidationError("Такое значение уже есть.")
        return name


class LeadBulkSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False, max_length=200)
    action = serializers.ChoiceField(choices=["status", "assign"])
    status = serializers.ChoiceField(choices=Lead.Status.choices, required=False)
    rejection_reason = serializers.PrimaryKeyRelatedField(
        queryset=LeadRejectionReason.objects.none(), required=False, allow_null=True
    )
    comment = serializers.CharField(required=False, allow_blank=True, default="")
    assigned_to = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.none(), required=False, allow_null=True
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            organization = request.user.organization
            self.fields["rejection_reason"].queryset = LeadRejectionReason.objects.for_tenant(
                organization
            ).filter(is_active=True)
            self.fields["assigned_to"].queryset = User.objects.filter(
                organization=organization, is_active=True
            )

    def validate(self, attrs):
        if attrs["action"] == "status":
            if not attrs.get("status"):
                raise serializers.ValidationError({"status": "Выберите статус."})
            # Массовый отказ — тоже только с причиной (критерий TRU-95).
            if attrs["status"] == Lead.Status.REJECTED and not attrs.get("rejection_reason"):
                raise serializers.ValidationError({"rejection_reason": "Укажите причину отказа."})
        elif "assigned_to" not in attrs:
            raise serializers.ValidationError({"assigned_to": "Выберите ответственного."})
        return attrs
