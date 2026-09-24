"""
Активный филиал для API (frontend2, TRU-80). В старом вебе выбор жил в
сессии (core.views.switch_branch); фронт на JWT присылает его заголовком
`X-Branch-Id` на каждый запрос.

Нет заголовка — «все филиалы» (None). Филиал чужой организации или
архивный — тоже None, а не ошибка: заголовок не должен ни ломать запрос,
ни открывать чужие данные. Списки, которые умеют фильтровать по филиалу,
берут его отсюда (список детей — TRU-81 и т.д.).
"""

import uuid

from domains.platform.tenants.models import Branch

HEADER = "HTTP_X_BRANCH_ID"


def get_active_branch(request):
    user = getattr(request, "user", None)
    raw = request.META.get(HEADER)
    if not raw or user is None or not user.is_authenticated or not user.organization_id:
        return None
    try:
        branch_id = uuid.UUID(raw)
    except ValueError:
        return None
    return Branch.objects.for_tenant(user.organization).filter(pk=branch_id, is_active=True).first()
