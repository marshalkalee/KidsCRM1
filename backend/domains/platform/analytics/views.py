"""
API аналитики (TRU-118) — один эндпоинт на все отчёты:

GET /api/v1/analytics/metrics/?metrics=revenue,visits&period=month
    &from=…&to=… (period=custom) &branch=<id>&branch=<id>
    &compare=0 (без прошлого периода) &series=0 (без графика)

GET /api/v1/analytics/catalog/ — какие метрики есть, какие филиалы доступны
    и какие периоды можно выбрать: для выбора периода и филиала в каркасе
    дашборда (TRU-113).
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from domains.platform.core.permissions import IsStaffOfOrganization
from domains.platform.core.role_permissions import can_view_analytics

from . import metrics  # noqa: F401 — регистрирует базовые метрики
from .period import PRESETS, PeriodError, parse_period
from .registry import REGISTRY, compute
from .scope import ScopeError, allowed_branch_ids, scope_for

# Больше метрик за запрос — это уже выгрузка, а не экран.
MAX_METRICS = 12


class CanViewAnalytics(BasePermission):
    def has_permission(self, request, view):
        return IsStaffOfOrganization().has_permission(request, view) and can_view_analytics(
            request.user
        )


def _flag(request, name):
    return request.query_params.get(name, "1") not in ("0", "false")


@api_view(["GET"])
@permission_classes([CanViewAnalytics])
def metrics_api(request, version=None):
    names = [n for n in request.query_params.get("metrics", "").split(",") if n]
    if not names:
        return Response({"metrics": ["Укажите метрики: ?metrics=revenue,visits"]}, status=400)
    if len(names) > MAX_METRICS:
        return Response({"metrics": [f"Не больше {MAX_METRICS} метрик за запрос."]}, status=400)
    unknown = [n for n in names if n not in REGISTRY]
    if unknown:
        return Response({"metrics": [f"Нет такой метрики: {', '.join(unknown)}"]}, status=400)
    try:
        period = parse_period(request.query_params, request.user.organization)
        scope = scope_for(request)
    except PeriodError as exc:
        return Response({"period": [str(exc)]}, status=400)
    except ScopeError as exc:
        return Response({"detail": str(exc)}, status=403)
    compare = _flag(request, "compare")
    return Response(
        {
            "period": period.as_dict(),
            "previous_period": period.previous().as_dict() if compare else None,
            "branches": [{"id": str(b.id), "name": b.name} for b in scope.branches],
            "all_branches": scope.branch_ids is None,
            "metrics": compute(
                names, scope, period, compare=compare, series=_flag(request, "series")
            ),
        }
    )


@api_view(["GET"])
@permission_classes([CanViewAnalytics])
def catalog_api(request, version=None):
    from domains.platform.tenants.models import Branch

    allowed = allowed_branch_ids(request.user)
    branches = Branch.objects.for_tenant(request.user.organization).filter(is_active=True)
    if allowed is not None:
        branches = branches.filter(pk__in=allowed)
    return Response(
        {
            "metrics": [
                {
                    "name": m.name,
                    "label": m.label,
                    "unit": m.unit,
                    "kind": m.kind,
                    "source": m.source,
                    "min_history_days": m.min_history_days,
                }
                for m in REGISTRY.values()
            ],
            "branches": [{"id": str(b.id), "name": b.name} for b in branches.order_by("name")],
            "can_see_all_branches": allowed is None,
            "periods": list(PRESETS),
        }
    )
