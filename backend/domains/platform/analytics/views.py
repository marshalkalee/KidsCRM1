"""
API аналитики (TRU-118) — один эндпоинт на все отчёты:

GET /api/v1/analytics/metrics/?metrics=revenue,visits&period=month
    &from=…&to=… (period=custom) &branch=<id>&branch=<id>
    &compare=0 (без прошлого периода) &series=0 (без графика)

GET /api/v1/analytics/breakdown/?metric=revenue&by=method&period=… — метрика
    по одному измерению (способ оплаты, филиал, направление, источник, статус).

GET /api/v1/analytics/heatmap/?period=… — посещения по дню недели и часу.

GET /api/v1/analytics/catalog/ — какие метрики есть, какие филиалы доступны
    и какие периоды можно выбрать: для выбора периода и филиала в каркасе
    дашборда (TRU-113).
"""

import uuid

from django.http import HttpResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from domains.platform.core.permissions import IsStaffOfOrganization
from domains.platform.core.role_permissions import can_view_analytics
from domains.scheduling.groups.queries import underfilled_threshold

from . import metrics  # noqa: F401 — регистрирует базовые метрики
from .breakdowns import BreakdownError, breakdown, visits_heatmap
from .export import filename, workbook
from .funnel import FILTERS as FUNNEL_FILTERS
from .funnel import FunnelError, funnel, funnel_by
from .group_occupancy import group_occupancy
from .period import PRESETS, PeriodError, parse_period
from .registry import REGISTRY, compute
from .reports import REPORTS, build
from .scope import ScopeError, allowed_branch_ids, scope_for
from .sources import SMALL_SAMPLE, sources_by_month, sources_quality

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


def _period_and_scope(request):
    """(period, scope, None) или (None, None, ответ с ошибкой)."""
    try:
        return (
            parse_period(request.query_params, request.user.organization),
            scope_for(request),
            None,
        )
    except PeriodError as exc:
        return None, None, Response({"period": [str(exc)]}, status=400)
    except ScopeError as exc:
        return None, None, Response({"detail": str(exc)}, status=403)


@api_view(["GET"])
@permission_classes([CanViewAnalytics])
def breakdown_api(request, version=None):
    period, scope, error = _period_and_scope(request)
    if error:
        return error
    name = request.query_params.get("metric", "")
    try:
        items = breakdown(name, request.query_params.get("by", ""), scope, period)
    except BreakdownError as exc:
        return Response({"by": [str(exc)]}, status=400)
    return Response({"period": period.as_dict(), "unit": REGISTRY[name].unit, "items": items})


@api_view(["GET"])
@permission_classes([CanViewAnalytics])
def heatmap_api(request, version=None):
    period, scope, error = _period_and_scope(request)
    if error:
        return error
    return Response({"period": period.as_dict(), "cells": visits_heatmap(scope, period)})


@api_view(["GET"])
@permission_classes([CanViewAnalytics])
def group_occupancy_api(request, version=None):
    """Заполняемость групп, недобор, динамика и разрезы (TRU-119)."""
    period, scope, error = _period_and_scope(request)
    if error:
        return error
    return Response(group_occupancy(scope, period, request.query_params))


def _funnel_filters(request):
    """?source=<id>&direction=<id>&manager=<id> — кривой id просто не находит."""
    filters = {}
    for name in FUNNEL_FILTERS:
        raw = request.query_params.get(name)
        if raw:
            try:
                filters[name] = uuid.UUID(raw)
            except ValueError:
                filters[name] = uuid.UUID(int=0)
    return filters


@api_view(["GET"])
@permission_classes([CanViewAnalytics])
def funnel_api(request, version=None):
    """Воронка новых заявок за период (TRU-115) + прошлый период."""
    period, scope, error = _period_and_scope(request)
    if error:
        return error
    return Response(
        {
            "period": period.as_dict(),
            "previous_period": period.previous().as_dict(),
            "funnel": funnel(scope, period, _funnel_filters(request)),
        }
    )


@api_view(["GET"])
@permission_classes([CanViewAnalytics])
def funnel_by_api(request, version=None):
    period, scope, error = _period_and_scope(request)
    if error:
        return error
    try:
        items = funnel_by(
            scope, period, request.query_params.get("by", ""), _funnel_filters(request)
        )
    except FunnelError as exc:
        return Response({"by": [str(exc)]}, status=400)
    return Response({"period": period.as_dict(), "items": items})


def _filter_labels(organization, filters):
    """Подписи фильтров воронки для шапки выгрузки: «Источник: Instagram»."""
    from domains.platform.leads.models import LeadSource
    from domains.platform.tenants.models import Direction
    from domains.platform.users.models import User

    models = {"source": ("Источник", LeadSource), "direction": ("Направление", Direction)}
    labels = []
    for name, value in filters.items():
        if name == "manager":
            user = User.objects.filter(organization=organization, pk=value).first()
            labels.append(f"Ответственный: {user.full_name if user else '—'}")
        else:
            title, model = models[name]
            row = model.objects.for_tenant(organization).filter(pk=value).first()
            labels.append(f"{title}: {row.name if row else '—'}")
    return labels


@api_view(["GET"])
@permission_classes([CanViewAnalytics])
def export_api(request, version=None):
    """GET /analytics/export/?report=revenue&period=…&branch=… — Excel
    отчёта с тем же периодом, филиалами и фильтрами, что на экране (TRU-114)."""
    name = request.query_params.get("report", "")
    if name not in REPORTS:
        return Response({"report": [f"Нет такого отчёта: {name}"]}, status=400)
    period, scope, error = _period_and_scope(request)
    if error:
        return error
    filters = _funnel_filters(request) if name in ("funnel", "sources") else {}
    if name == "sources":
        filters = {key: value for key, value in filters.items() if key == "direction"}
    report_params = {
        "funnel_filters": filters,
        "filter_labels": _filter_labels(scope.organization, filters),
    }
    if name == "group_occupancy":
        report_params["occupancy_filters"] = request.query_params
    export = build(
        name,
        scope,
        period,
        report_params,
    )
    response = HttpResponse(
        workbook(export, scope, period),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename(name, period)}"'
    return response


@api_view(["GET"])
@permission_classes([CanViewAnalytics])
def sources_api(request, version=None):
    """Качество источников заявок за период (TRU-116): воронка по источнику,
    средний чек, помета малой выборки, заявки и покупки по месяцам."""
    period, scope, error = _period_and_scope(request)
    if error:
        return error
    filters = {k: v for k, v in _funnel_filters(request).items() if k == "direction"}
    return Response(
        {
            "period": period.as_dict(),
            "small_sample": SMALL_SAMPLE,
            "items": sources_quality(scope, period, filters),
            "by_month": sources_by_month(scope, period, filters),
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
            # Порог «группа недозаполнена» — отметка на шкале заполняемости.
            "group_underfilled_percent": underfilled_threshold(request.user.organization),
        }
    )
