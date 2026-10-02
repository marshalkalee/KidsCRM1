"""Публичный эндпоинт приёма заявок с сайта (ТЗ п. 5.1, п. 10.3; TRU-110).

Единственная точка входа без аутентификации — требования к ней строже:
organization/branch — по непредсказуемому ключу (не по внутреннему id),
rate limit по IP и по ключу, honeypot, защита от дублей, CORS только для
домена центра. Ответ никогда не отличается в зависимости от того, что
реально произошло (дубль/honeypot/успех) — иначе через разницу в ответе
можно проверять, есть ли в базе конкретный ребёнок или телефон (ТЗ п. 10.3,
утечка ПДн несовершеннолетних).
"""

from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle
from rest_framework.views import APIView

from domains.platform.tenants.models import Branch, Organization

from .models import Lead, LeadComment, LeadSource
from .public_serializers import PublicLeadSerializer

DUPLICATE_WINDOW_MINUTES = 10

# Единственный ответ на любой исход — успех, honeypot, дубль, невалидный
# ключ. Без этого разница в ответе сама по себе стала бы утечкой (ТЗ п. 10.3).
_GENERIC_OK = {"status": "accepted"}


class PublicLeadIpThrottle(AnonRateThrottle):
    scope = "public_lead_ip"
    THROTTLE_RATES = {"public_lead_ip": "10/hour"}


class PublicLeadOrgThrottle(SimpleRateThrottle):
    """Ограничение по ключу организации — отдельно от IP: у центра форма
    может собирать обращения с разных устройств/сетей, но суммарный поток
    на одну организацию всё равно должен быть ограничен."""

    scope = "public_lead_org"
    THROTTLE_RATES = {"public_lead_org": "100/hour"}

    def get_cache_key(self, request, view):
        public_key = view.kwargs.get("public_key", "")
        return self.cache_format % {"scope": self.scope, "ident": public_key}


class PublicLeadCreateView(APIView):
    authentication_classes = []
    permission_classes = []
    throttle_classes = [PublicLeadIpThrottle, PublicLeadOrgThrottle]

    def _organization(self):
        return Organization.objects.filter(
            public_api_key=self.kwargs.get("public_key"), is_active=True
        ).first()

    def _cors_origin(self, organization):
        return organization.website_domain if organization and organization.website_domain else None

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        origin = self._cors_origin(self._organization())
        request_origin = request.META.get("HTTP_ORIGIN")
        if origin and request_origin == origin:
            response["Access-Control-Allow-Origin"] = origin
            response["Vary"] = "Origin"
        return response

    def options(self, request, *args, **kwargs):
        response = Response(status=status.HTTP_200_OK)
        origin = self._cors_origin(self._organization())
        request_origin = request.META.get("HTTP_ORIGIN")
        if origin and request_origin == origin:
            response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
            response["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    def post(self, request, *args, **kwargs):
        organization = self._organization()
        if organization is None:
            # Неверный/неактивный ключ — тот же ответ, что и успех: не
            # подтверждаем и не опровергаем существование ключа наружу.
            return Response(_GENERIC_OK, status=status.HTTP_201_CREATED)

        serializer = PublicLeadSerializer(data=request.data)
        if not serializer.is_valid():
            # Отдельно от утечки ПДн: ошибки ВВОДА (невалидный формат) можно
            # показывать — это не раскрывает ничьи данные, просто помогает
            # настоящему человеку поправить форму.
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data

        if data["website"]:
            # Honeypot сработал — тихо делаем вид, что всё хорошо.
            return Response(_GENERIC_OK, status=status.HTTP_201_CREATED)

        branch = None
        if data["branch_id"]:
            branch = Branch.objects.filter(
                organization=organization, pk=data["branch_id"], is_active=True
            ).first()

        direction = None
        if data["direction_id"]:
            from domains.platform.tenants.models import Direction

            direction = Direction.objects.filter(
                organization=organization, pk=data["direction_id"], is_active=True
            ).first()

        recent_cutoff = timezone.now() - timedelta(minutes=DUPLICATE_WINDOW_MINUTES)
        is_duplicate = (
            Lead.objects.for_tenant(organization)
            .filter(phone=data["phone"], created_at__gte=recent_cutoff)
            .exists()
        )
        if is_duplicate:
            return Response(_GENERIC_OK, status=status.HTTP_201_CREATED)

        source, _created = LeadSource.objects.get_or_create(
            organization=organization, name="Сайт", defaults={"is_active": True}
        )

        lead = Lead.objects.create(
            organization=organization,
            kind=Lead.Kind.NEW,
            status=Lead.Status.NEW,
            branch=branch,
            parent_name=data["parent_name"],
            phone=data["phone"],
            child_name=data["child_name"],
            child_age=data["child_age"],
            direction=direction,
            source=source,
        )
        if data["comment"]:
            LeadComment.objects.create(
                organization=organization, lead=lead, author=None, text=data["comment"]
            )

        return Response(_GENERIC_OK, status=status.HTTP_201_CREATED)
