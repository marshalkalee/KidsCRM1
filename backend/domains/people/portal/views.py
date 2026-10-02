"""API кабинета родителя: /api/v1/portal/ (TRU-135)."""

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import account
from .auth import LoginError, logout, request_code, verify_code
from .authentication import IsParent, ParentTokenAuthentication, request_meta
from .models import ParentSession


def _error(exc: LoginError):
    response = Response({"detail": str(exc)}, status=exc.status)
    if exc.retry_after:
        response["Retry-After"] = str(exc.retry_after)
    return response


class PublicView(APIView):
    # Без токена: старый JWT сотрудника или протухший токен родителя в
    # браузере не должен ронять вход.
    authentication_classes = []
    permission_classes = [AllowAny]


class RequestCodeView(PublicView):
    def post(self, request, version=None):
        try:
            return Response(request_code(request.data.get("phone", ""), request_meta(request)))
        except LoginError as exc:
            return _error(exc)


class VerifyCodeView(PublicView):
    def post(self, request, version=None):
        try:
            return Response(
                verify_code(
                    request.data.get("phone", ""),
                    request.data.get("code", ""),
                    request_meta(request),
                )
            )
        except LoginError as exc:
            return _error(exc)


class ParentView(APIView):
    authentication_classes = [ParentTokenAuthentication]
    permission_classes = [IsParent]


class LogoutView(ParentView):
    def post(self, request, version=None):
        logout(request.auth, request_meta(request), everywhere=bool(request.data.get("everywhere")))
        return Response(status=status.HTTP_204_NO_CONTENT)


class SessionsView(ParentView):
    """Устройства, где родитель вошёл, — чтобы отозвать потерянный телефон."""

    def get(self, request, version=None):
        rows = ParentSession.objects.filter(account=request.user, revoked_at__isnull=True)
        return Response(
            [
                {
                    "id": str(s.id),
                    "user_agent": s.user_agent,
                    "created_at": s.created_at,
                    "last_seen_at": s.last_seen_at,
                    "current": s.pk == request.auth.pk,
                }
                for s in rows
            ]
        )


class SessionDetailView(ParentView):
    def delete(self, request, session_id, version=None):
        from django.utils import timezone

        updated = ParentSession.objects.filter(
            account=request.user, pk=session_id, revoked_at__isnull=True
        ).update(revoked_at=timezone.now())
        if not updated:
            return Response({"detail": "Не найдено."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(ParentView):
    """Кто вошёл, его профиль и все его дети — первый запрос кабинета."""

    def get(self, request, version=None):
        return Response(
            {**account.profile(request.user), "children": account.children(request.user)}
        )


class ChildDetailView(ParentView):
    """Один ребёнок родителя. Чужой и несуществующий — одинаково 404."""

    def get(self, request, child_id, version=None):
        for child in account.children(request.user):
            if child["id"] == str(child_id):
                return Response(child)
        return Response({"detail": "Не найдено."}, status=status.HTTP_404_NOT_FOUND)


class ProfileView(ParentView):
    def get(self, request, version=None):
        return Response(account.profile(request.user))

    def patch(self, request, version=None):
        try:
            return Response(
                account.update_profile(
                    request.user,
                    email=request.data.get("email"),
                    language=request.data.get("language"),
                )
            )
        except LoginError as exc:
            return _error(exc)


class PhoneChangeView(ParentView):
    """Смена телефона: {phone} — код на новый номер; {phone, code} — сменить."""

    def post(self, request, version=None):
        try:
            if request.data.get("code"):
                result = account.confirm_phone_change(
                    request.user,
                    request.data.get("phone", ""),
                    request.data["code"],
                    request_meta(request),
                )
            else:
                result = account.request_phone_change(
                    request.user, request.data.get("phone", ""), request_meta(request)
                )
            return Response(result)
        except LoginError as exc:
            return _error(exc)
