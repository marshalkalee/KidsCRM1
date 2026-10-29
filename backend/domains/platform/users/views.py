from django.db.models import Exists, OuterRef
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from domains.platform.core.active_branch import branch_scope
from domains.platform.core.audit import AuditLog
from domains.platform.core.images import clean_image, delete_image, save_image
from domains.platform.core.permissions import IsOwnerOrManager, IsStaffOfOrganization
from domains.platform.core.role_permissions import OVERRIDABLE, access_items, get_user_permissions
from domains.platform.notifications.messaging import telephony
from domains.platform.users.serializers import (
    ChangePasswordSerializer,
    CustomTokenObtainSerializer,
    InviteStaffSerializer,
    OrganizationRegisterSerializer,
    ProfileSerializer,
)

from .models import User
from .serializers import UserSerializer


class UserViewSet(viewsets.ModelViewSet):
    """
    Сотрудники организации. Смотреть — всем сотрудникам (выбор
    преподавателя в группе и расписании). Заводить, менять, удалять — только
    владелец и управляющий (TRU-90: раньше это мог любой сотрудник, включая
    смену себе роли на «владелец»). Ролевые ограничения — check_role_change.
    """

    serializer_class = UserSerializer
    permission_classes = [IsStaffOfOrganization]

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy", "access"):
            return [IsOwnerOrManager()]
        return [IsStaffOfOrganization()]

    def get_queryset(self):
        qs = User.objects.filter(organization=self.request.user.organization)
        scope = branch_scope(self.request, self.request.query_params.get("branch"))
        if scope is not None:
            in_my_branches = User.branches.through.objects.filter(
                user_id=OuterRef("pk"), branch_id__in=scope
            )
            no_branches = ~Exists(User.branches.through.objects.filter(user_id=OuterRef("pk")))
            qs = qs.filter(Exists(in_my_branches) | no_branches)
        role = self.request.query_params.get("role")
        if role:
            qs = qs.filter(role=role)
        return qs.order_by("full_name")

    def perform_destroy(self, instance):
        from rest_framework.exceptions import ValidationError

        if instance.pk == self.request.user.pk:
            raise ValidationError({"detail": "Нельзя удалить самого себя."})
        if instance.role == User.Role.OWNER and self.request.user.role != User.Role.OWNER:
            raise ValidationError({"detail": "Удалить владельца может только владелец."})
        instance.delete()

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)

    @action(detail=True, methods=["get", "put"])
    def access(self, request, pk=None, version=None):
        """Особые права сотрудника поверх роли. Смотрят владелец и управляющий,
        меняет только владелец — иначе управляющий открыл бы себе что угодно.
        PUT {"overrides": {"can_view_phone": true, "can_accept_payments": null}}:
        null или совпадение с ролью — «как у роли»."""
        target = self.get_object()
        editable = request.user.role == User.Role.OWNER and target.role != User.Role.OWNER
        if request.method == "PUT":
            if not editable:
                detail = (
                    "У владельца все права — менять нечего."
                    if target.role == User.Role.OWNER
                    else "Особые права меняет только владелец."
                )
                return Response({"detail": detail}, status=status.HTTP_403_FORBIDDEN)
            incoming = request.data.get("overrides") if isinstance(request.data, dict) else None
            if not isinstance(incoming, dict) or any(
                key not in OVERRIDABLE or not (value is None or isinstance(value, bool))
                for key, value in incoming.items()
            ):
                return Response(
                    {"detail": "Неизвестное право или значение."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            before = dict(target.permission_overrides or {})
            merged = {**before, **incoming}
            defaults = {item["key"]: item["role_default"] for item in access_items(target)}
            # Храним только отличия от роли: сменят роль — лишнего не останется.
            target.permission_overrides = {
                key: value
                for key, value in merged.items()
                if isinstance(value, bool) and value != defaults[key]
            }
            if target.permission_overrides != before:
                target.save(update_fields=["permission_overrides", "updated_at"])
                AuditLog.record(
                    actor=request.user,
                    action=AuditLog.Action.GRANT,
                    entity=target,
                    before={"permission_overrides": before},
                    after={"permission_overrides": target.permission_overrides},
                )
        return Response({"editable": editable, "role": target.role, "items": access_items(target)})


@method_decorator(ratelimit(key="ip", rate="5/m", method="POST", block=True), name="post")
class RegisterView(APIView):
    permission_classes = [AllowAny]
    # Регистрация без токена: старый токен в браузере (например, отключённого
    # пользователя) не должен мешать завести новый центр.
    authentication_classes = []

    def post(self, request):
        serializer = OrganizationRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        org, user = serializer.save()
        refresh = RefreshToken.for_user(user)
        refresh["organization_id"] = str(org.id)
        refresh["role"] = user.role
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "organization": {"id": str(org.id), "name": org.name, "slug": org.slug},
            },
            status=status.HTTP_201_CREATED,
        )


@method_decorator(ratelimit(key="ip", rate="5/m", method="POST", block=True), name="post")
class LoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainSerializer


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            token = RefreshToken(request.data["refresh"])
            token.blacklist()
        except Exception:
            pass
        return Response(status=status.HTTP_204_NO_CONTENT)


class LogoutAllView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

        for token in OutstandingToken.objects.filter(user=request.user):
            try:
                RefreshToken(token.token).blacklist()
            except Exception:
                pass
        return Response(status=status.HTTP_204_NO_CONTENT)


class InviteStaffView(APIView):
    # Раньше — любой вошедший пользователь с любой ролью в запросе (TRU-90).
    permission_classes = [IsOwnerOrManager]

    def post(self, request):
        serializer = InviteStaffSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {"id": str(user.id), "full_name": user.full_name, "role": user.role},
            status=status.HTTP_201_CREATED,
        )


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"detail": "Пароль изменён."})


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(self.payload(request.user))

    def patch(self, request):
        serializer = ProfileSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(self.payload(request.user))

    @staticmethod
    def payload(user):
        return {
            "id": str(user.id),
            "full_name": user.full_name,
            "phone": user.phone,
            "role": user.role,
            "photo_url": user.photo_url,
            "organization_id": str(user.organization_id) if user.organization_id else None,
            # Название — в готовом тексте WhatsApp из карточки заявки (TRU-96).
            "organization_name": user.organization.name if user.organization_id else None,
            "branches": [str(b.id) for b in user.branches.all()],
            "permissions": get_user_permissions(user),
            # Кнопки «Позвонить» — только когда звонок пойдёт через АТС.
            "can_call": bool(
                user.organization_id
                and user.role in (User.Role.OWNER, User.Role.MANAGER, User.Role.ADMIN)
                and telephony.can_call_out(user.organization)
            ),
        }


PHOTO_FOLDER = "users/photos"


class MePhotoView(APIView):
    """Своё фото: multipart file → новая ссылка в профиле; DELETE — убрать.
    Прежний файл удаляется, чтобы снятое фото не оставалось на сервере."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        uploaded, error = clean_image(request.FILES)
        if error:
            return Response({"file": [error]}, status=status.HTTP_400_BAD_REQUEST)
        self._replace(request.user, save_image(request, uploaded, PHOTO_FOLDER))
        return Response(MeView.payload(request.user))

    def delete(self, request):
        self._replace(request.user, "")
        return Response(MeView.payload(request.user))

    @staticmethod
    def _replace(user, url):
        old = user.photo_url
        user.photo_url = url
        user.save(update_fields=["photo_url", "updated_at"])
        if old:
            delete_image(old, PHOTO_FOLDER)
