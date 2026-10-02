"""
Объявления центра — сторона сотрудников (TRU-140): /api/v1/announcements/.
Пишут владелец, управляющий и администратор (can_manage_announcements);
черновик → «Опубликовать». Вложение — картинка или PDF до 10 МБ.
"""

import uuid
from pathlib import Path

from django.core.files.storage import default_storage
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from domains.platform.core.audit import AuditLog
from domains.platform.core.permissions import IsOwnerOrManagerOrAdmin

from . import announcements
from .models import Announcement

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
ALLOWED_ATTACHMENTS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
TARGETS = ("branch", "direction", "group")


class AnnouncementSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    audience_display = serializers.CharField(source="get_audience_display", read_only=True)
    target_name = serializers.SerializerMethodField()
    reach = serializers.SerializerMethodField()

    class Meta:
        model = Announcement
        fields = [
            "id",
            "title",
            "body",
            "status",
            "status_display",
            "published_at",
            "expires_on",
            "audience",
            "audience_display",
            "branch",
            "direction",
            "group",
            "target_name",
            "attachment_url",
            "attachment_name",
            "reach",
            "created_at",
        ]
        read_only_fields = ["status", "published_at", "created_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            organization = request.user.organization
            # Иначе можно адресовать объявление группе чужого центра.
            for key in TARGETS:
                field = self.fields[key]
                field.queryset = field.queryset.filter(organization=organization)

    def get_target_name(self, obj):
        target = getattr(obj, obj.audience, None) if obj.audience in TARGETS else None
        return target.name if target else ""

    def get_reach(self, obj):
        return announcements.reach(obj)

    def validate(self, attrs):
        instance = self.instance
        audience = attrs.get(
            "audience", getattr(instance, "audience", Announcement.Audience.ORGANIZATION)
        )
        needed = audience if audience in TARGETS else None
        if needed and not attrs.get(needed, getattr(instance, needed, None)):
            raise serializers.ValidationError({needed: ["Выберите, кому адресовано объявление."]})
        # Лишние цели убираем: в базе не бывает «группа и филиал» сразу.
        for key in TARGETS:
            if key != needed:
                attrs[key] = None
        title = attrs.get("title", getattr(instance, "title", "")) or ""
        if not title.strip():
            raise serializers.ValidationError({"title": ["Напишите заголовок."]})
        return attrs


class AnnouncementViewSet(viewsets.ModelViewSet):
    serializer_class = AnnouncementSerializer
    permission_classes = [IsOwnerOrManagerOrAdmin]

    def get_queryset(self):
        return (
            Announcement.objects.for_tenant(self.request.user.organization)
            .select_related("branch", "direction", "group", "organization")
            .order_by("-created_at")
        )

    def _audit(self, action, entity, **data):
        AuditLog.record(actor=self.request.user, action=action, entity=entity, after=data or None)

    def perform_create(self, serializer):
        announcement = serializer.save(
            organization=self.request.user.organization, created_by=self.request.user
        )
        self._audit(AuditLog.Action.CREATE, announcement, title=announcement.title)

    def perform_update(self, serializer):
        announcement = serializer.save()
        self._audit(AuditLog.Action.UPDATE, announcement, title=announcement.title)

    def perform_destroy(self, instance):
        instance.delete()  # мягкое удаление — пропадает и у родителей
        self._audit(AuditLog.Action.DELETE, instance, title=instance.title)

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        announcement = self.get_object()
        if announcement.status != Announcement.Status.PUBLISHED:
            announcement.status = Announcement.Status.PUBLISHED
            announcement.published_at = timezone.now()
            announcement.save(update_fields=["status", "published_at", "updated_at"])
            self._audit(AuditLog.Action.UPDATE, announcement, status="published")
        return Response(self.get_serializer(announcement).data)

    @action(detail=True, methods=["post"])
    def unpublish(self, request, pk=None):
        """Снять с публикации — снова черновик, у родителей пропадает."""
        announcement = self.get_object()
        announcement.status = Announcement.Status.DRAFT
        announcement.save(update_fields=["status", "updated_at"])
        self._audit(AuditLog.Action.UPDATE, announcement, status="draft")
        return Response(self.get_serializer(announcement).data)

    @action(detail=False, methods=["post"])
    def attachment(self, request):
        uploaded = request.FILES.get("file")
        if uploaded is None:
            return Response({"file": ["Выберите файл."]}, status=status.HTTP_400_BAD_REQUEST)
        extension = Path(uploaded.name).suffix.lower()
        if extension not in ALLOWED_ATTACHMENTS:
            return Response(
                {"file": ["Картинка (JPG, PNG) или PDF."]}, status=status.HTTP_400_BAD_REQUEST
            )
        if uploaded.size > MAX_ATTACHMENT_BYTES:
            return Response({"file": ["Файл больше 10 МБ."]}, status=status.HTTP_400_BAD_REQUEST)
        path = default_storage.save(f"announcements/{uuid.uuid4()}{extension}", uploaded)
        return Response(
            {
                "url": request.build_absolute_uri(default_storage.url(path)),
                "name": Path(uploaded.name).name[:200],
            },
            status=status.HTTP_201_CREATED,
        )
