"""
Отчёт по причинам отказов (TRU-117, ТЗ п. 5.3).

Считаем отказы, случившиеся за период (дата перехода в «Отказ» из истории
статусов, TRU-99), — не заявки, созданные за период: вопрос «почему нам
отказывали в сентябре», а не «что стало с сентябрьскими заявками».

- Этап отказа — из какого статуса заявка ушла в отказ: сразу после звонка
  и после посещённого пробного — разные проблемы (цена и ожидания против
  занятия и преподавателя).
- «Не пришёл на пробное» и другие причины с признаком потери контакта
  (`LeadRejectionReason.is_lost_contact`) — отдельно: это не возражение, а
  потерянный контакт, иначе он размывает картину реальных причин.
- Новые заявки и продления — разные воронки (TRU-98), считаются отдельно.
"""

from collections import Counter, defaultdict

import pytz
from django.db.models.functions import TruncMonth

from domains.platform.leads.models import Lead, LeadKind, LeadStatusChange

from .breakdowns import DIMENSIONS
from .registry import cached

S = Lead.Status
# Этапы, на которых отказывают: из какого статуса ушли в отказ.
STAGES = [
    ("before_contact", "До разговора", {S.NEW}),
    ("after_contact", "После звонка", {S.CONTACTED, S.THINKING}),
    ("trial_booked", "Записан на пробное", {S.TRIAL_SCHEDULED}),
    ("after_trial", "После пробного", {S.TRIAL_ATTENDED}),
]
STAGE_OF = {status: key for key, _, statuses in STAGES for status in statuses}
DIMENSION_FIELDS = {
    "source": "lead__source_id",
    "direction": "lead__direction_id",
    "branch": "lead__branch_id",
}
COMMENTS_LIMIT = 100


class RejectionError(ValueError):
    pass


def _key(kind, scope, period, filters):
    return f"{kind}:{scope.cache_key}:{period.start}:{period.end}:{sorted((filters or {}).items())}"


def _rejections(scope, period, kind, filters):
    start, end = period.bounds(scope.organization)
    qs = LeadStatusChange.objects.filter(
        lead__organization=scope.organization,
        lead__kind=kind,
        to_status=S.REJECTED,
        changed_at__gte=start,
        changed_at__lt=end,
    ).order_by()
    qs = scope.filter(qs, "lead__branch_id")
    for name in ("source", "direction"):
        if (filters or {}).get(name):
            qs = qs.filter(**{DIMENSION_FIELDS[name]: filters[name]})
    return qs


def rejections(scope, period, kind=LeadKind.NEW, filters=None):
    if kind not in LeadKind.values:
        raise RejectionError("Вид заявок: new или renewal.")

    def run():
        tz = pytz.timezone(scope.organization.timezone)
        rows = list(
            _rejections(scope, period, kind, filters)
            .annotate(month=TruncMonth("changed_at", tzinfo=tz))
            .values_list(
                "from_status",
                "rejection_reason_id",
                "rejection_reason__name",
                "rejection_reason__is_lost_contact",
                "month",
            )
        )
        by_reason = Counter()
        names = {}
        lost = Counter()
        matrix = defaultdict(Counter)
        monthly = defaultdict(Counter)
        stages = Counter()
        for from_status, reason_id, name, is_lost, month in rows:
            names[reason_id] = name
            stage = STAGE_OF.get(from_status, "after_contact")
            if is_lost:
                lost[reason_id] += 1
                continue
            by_reason[reason_id] += 1
            matrix[reason_id][stage] += 1
            stages[stage] += 1
            monthly[month.date().replace(day=1).isoformat()][reason_id] += 1
        real = sum(by_reason.values())
        return {
            "total": len(rows),
            "real": real,
            "lost_contact": sum(lost.values()),
            "lost_contact_reasons": [
                {"key": str(k) if k else None, "label": names[k], "value": v}
                for k, v in lost.most_common()
            ],
            "reasons": [
                {
                    "key": str(reason_id) if reason_id else None,
                    "label": names[reason_id],
                    "value": count,
                    "share": round(count * 100 / real, 1) if real else None,
                    "stages": {key: matrix[reason_id][key] for key, _, _ in STAGES},
                }
                for reason_id, count in by_reason.most_common()
            ],
            "stages": [
                {"key": key, "label": label, "value": stages[key]} for key, label, _ in STAGES
            ],
            "by_month": [
                {"month": month, "key": str(k) if k else None, "label": names[k], "value": v}
                for month in sorted(monthly)
                for k, v in monthly[month].most_common()
            ],
        }

    key = f"rj:{_key(kind, scope, period, filters)}"
    return cached(key, period, scope, run)


def rejections_by(scope, period, dimension, kind=LeadKind.NEW, filters=None):
    """Отказы по источнику / направлению / филиалу: сколько и главная причина."""
    if dimension not in DIMENSION_FIELDS:
        raise RejectionError("Разрез: source, direction или branch.")

    def run():
        rows = list(
            _rejections(scope, period, kind, filters)
            .exclude(rejection_reason__is_lost_contact=True)
            .values_list(DIMENSION_FIELDS[dimension], "rejection_reason__name")
        )
        groups = defaultdict(Counter)
        for key, reason in rows:
            groups[key][reason] += 1
        labels = DIMENSIONS[dimension](scope.organization, list(groups))
        items = []
        for key, reasons in groups.items():
            total = sum(reasons.values())
            top, top_count = reasons.most_common(1)[0]
            items.append(
                {
                    "key": str(key) if key else None,
                    "label": labels.get(key) if key else None,
                    "value": total,
                    "top_reason": top,
                    "top_share": round(top_count * 100 / total, 1),
                }
            )
        return sorted(
            items, key=lambda item: (-item["value"], item["label"] is None, item["label"] or "")
        )

    key = f"rjb:{dimension}:{_key(kind, scope, period, filters)}"
    return cached(key, period, scope, run)


def rejection_comments(scope, period, kind=LeadKind.NEW, filters=None):
    """Отказы с комментарием — читаемым списком, свежие сверху: в свободном
    тексте бывает то, чего нет в справочнике. Не кэшируется — живой список."""
    rows = (
        _rejections(scope, period, kind, filters)
        .exclude(comment="")
        .select_related("lead", "rejection_reason", "changed_by")
        .order_by("-changed_at")[:COMMENTS_LIMIT]
    )
    stage_label = {key: label for key, label, _ in STAGES}
    return [
        {
            "lead_id": str(row.lead_id),
            "lead": row.lead.child_name or row.lead.parent_name,
            "date": row.changed_at.isoformat(),
            "reason": row.rejection_reason.name if row.rejection_reason else None,
            "lost_contact": bool(row.rejection_reason and row.rejection_reason.is_lost_contact),
            "stage": stage_label[STAGE_OF.get(row.from_status, "after_contact")],
            "comment": row.comment,
            "author": row.changed_by.full_name if row.changed_by else None,
        }
        for row in rows
    ]
