"""API кабинета родителя: /api/v1/portal/ (TRU-135)."""

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import access
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
    """Кто вошёл и какие дети ему видны (подробности — TRU-136)."""

    def get(self, request, version=None):
        children = access.children_for_phone(request.user.phone)
        return Response(
            {
                "phone": request.user.phone,
                "language": request.user.language,
                "children": [
                    {
                        "id": str(child.id),
                        "full_name": child.full_name,
                        "status": child.status,
                        "organization": child.organization.name,
                    }
                    for child in children
                ],
            }
        )
