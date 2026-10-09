"""Ключи API в CRM (TRU-176): владелец выдаёт, отзывает, смотрит журнал."""

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from domains.platform.core.audit import AuditLog
from domains.platform.core.permissions import IsOwner
from domains.platform.tenants.models import Branch
from domains.platform.tenants.plans import has_feature

from .auth import issue_key
from .models import ApiKey, ApiRequestLog

LOG_LIMIT = 200


def _row(key):
    return {
        "id": str(key.id),
        "name": key.name,
        "prefix": key.prefix,
        "scope": key.scope,
        "scope_label": key.get_scope_display(),
        "branches": [{"id": str(b.id), "name": b.name} for b in key.branches.all()],
        "created_at": key.created_at,
        "created_by": key.created_by.full_name if key.created_by else "",
        "last_used_at": key.last_used_at,
        "revoked_at": key.revoked_at,
    }


@api_view(["GET", "POST"])
@permission_classes([IsOwner])
def keys(request, version=None):
    organization = request.user.organization
    if request.method == "POST":
        name = (request.data.get("name") or "").strip()[:100]
        scope = request.data.get("scope") or ApiKey.Scope.READ
        if not name:
            return Response({"name": ["Назовите ключ: «Сайт», «1С»…"]}, status=400)
        if scope not in ApiKey.Scope.values:
            return Response({"scope": ["Только чтение или чтение и запись."]}, status=400)
        branch_ids = request.data.get("branches") or []
        branches = list(Branch.objects.filter(organization=organization, pk__in=branch_ids))
        if len(branches) != len(set(map(str, branch_ids))):
            return Response({"branches": ["Нет такого филиала."]}, status=400)
        key, raw = issue_key(
            organization, name=name, scope=scope, branches=branches, user=request.user
        )
        AuditLog.record(
            actor=request.user,
            action=AuditLog.Action.GRANT,
            entity=key,
            after={"name": name, "scope": scope, "branches": [str(b.id) for b in branches]},
        )
        # Ключ целиком — один раз, в этом ответе.
        return Response({**_row(key), "key": raw}, status=status.HTTP_201_CREATED)
    rows = ApiKey.objects.for_tenant(organization).select_related("created_by")
    return Response(
        {
            "enabled": has_feature(organization, "public_api"),
            "keys": [_row(k) for k in rows.prefetch_related("branches")],
            "branches": [
                {"id": str(b.id), "name": b.name}
                for b in Branch.objects.filter(organization=organization).order_by("name")
            ],
            "docs_url": "/api/public/v1/docs/",
        }
    )


@api_view(["POST"])
@permission_classes([IsOwner])
def revoke(request, key_id, version=None):
    key = ApiKey.objects.for_tenant(request.user.organization).filter(pk=key_id).first()
    if key is None:
        return Response({"detail": "Ключ не найден."}, status=404)
    if key.revoked_at is None:
        key.revoked_at = timezone.now()
        key.revoked_by = request.user
        key.save(update_fields=["revoked_at", "revoked_by", "updated_at"])
        AuditLog.record(
            actor=request.user, action=AuditLog.Action.REVOKE, entity=key, after={"revoked": True}
        )
    return Response(_row(key))


@api_view(["GET"])
@permission_classes([IsOwner])
def request_log(request, version=None):
    rows = ApiRequestLog.objects.filter(organization=request.user.organization).select_related(
        "key"
    )
    if value := request.query_params.get("key"):
        rows = rows.filter(key_id=value)
    return Response(
        [
            {
                "id": str(r.id),
                "created_at": r.created_at,
                "key": r.key.name,
                "method": r.method,
                "path": r.path,
                "status": r.status,
                "ip": r.ip,
            }
            for r in rows[:LOG_LIMIT]
        ]
    )
