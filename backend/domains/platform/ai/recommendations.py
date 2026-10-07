"""Память рекомендаций: отклонённое и неизменное не повторяется бесконечно."""

import hashlib
import json

from django.db import transaction
from django.utils import timezone

from .models import AIRecommendationState


def _fingerprint(item):
    stable = {
        "candidate_key": item["candidate_key"],
        "case": item["case"],
        "basis": item["basis"],
    }
    return hashlib.sha256(
        json.dumps(stable, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def remember(organization, result, _snapshot):
    visible = []
    with transaction.atomic():
        for item in result.get("recommendations", []):
            fingerprint = _fingerprint(item)
            state, _ = AIRecommendationState.objects.select_for_update().get_or_create(
                organization=organization,
                function="group_promotion",
                fingerprint=fingerprint,
                defaults={"candidate_key": item["candidate_key"]},
            )
            if state.status == AIRecommendationState.Status.DISMISSED or state.times_shown >= 3:
                continue
            state.times_shown += 1
            state.payload = item
            state.last_seen_at = timezone.now()
            state.save(update_fields=["times_shown", "payload", "last_seen_at", "updated_at"])
            visible.append({**item, "recommendation_id": str(state.id)})
    return {**result, "recommendations": visible}


def dismiss(organization, recommendation_id):
    state = AIRecommendationState.objects.for_tenant(organization).get(pk=recommendation_id)
    state.status = AIRecommendationState.Status.DISMISSED
    state.save(update_fields=["status", "updated_at"])
    return state
