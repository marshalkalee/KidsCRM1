from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from domains.platform.core.images import clean_image, delete_image, save_image
from domains.platform.core.permissions import IsOwnerOrManager, IsStaffOfOrganization
from domains.platform.core.role_permissions import get_user_permissions
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
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsOwnerOrManager()]
        return [IsStaffOfOrganization()]

    def get_queryset(self):
        qs = User.objects.filter(organization=self.request.user.organization)
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
