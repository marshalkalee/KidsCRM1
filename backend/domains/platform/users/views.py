from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from domains.platform.core.permissions import IsStaffOfOrganization
from domains.platform.core.role_permissions import get_user_permissions
from domains.platform.users.serializers import (
    ChangePasswordSerializer,
    CustomTokenObtainSerializer,
    InviteStaffSerializer,
    OrganizationRegisterSerializer,
)

from .models import User
from .serializers import UserSerializer


class UserViewSet(viewsets.ModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [IsStaffOfOrganization]

    def get_queryset(self):
        return User.objects.filter(organization=self.request.user.organization)

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)


class RegisterView(APIView):
    permission_classes = [AllowAny]

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
    permission_classes = [IsAuthenticated]

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
        user = request.user
        return Response(
            {
                "id": str(user.id),
                "full_name": user.full_name,
                "phone": user.phone,
                "role": user.role,
                "organization_id": str(user.organization_id) if user.organization_id else None,
                "branches": [str(b.id) for b in user.branches.all()],
                "permissions": get_user_permissions(user),
            }
        )
