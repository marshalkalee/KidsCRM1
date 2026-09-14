from django.http import JsonResponse
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from domains.platform.tenants.models import Organization


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.authenticator = JWTAuthentication()

    def __call__(self, request):
        request.organization = None

        try:
            result = self.authenticator.authenticate(request)
            if result is not None:
                user, token = result
                org_id = token.get("organization_id")
                if org_id:
                    request.organization = Organization.objects.filter(
                        id=org_id,
                        is_active=True,
                        deleted_at__isnull=True,
                    ).first()
        except (InvalidToken, TokenError):
            pass

        return self.get_response(request)