"""
Какие филиалы попадают в отчёт (TRU-118, ТЗ п. 2). Один разбор на все
отчёты: владелец — любой набор филиалов или вся организация; управляющий
и остальные с закреплёнными филиалами — только свои. Чужой филиал в
запросе не ошибка, а просто не попадает в выборку: ссылку из чата
владельца управляющий откроет, но увидит только своё.
"""

import uuid
from dataclasses import dataclass, field

from domains.platform.core.active_branch import get_active_branch
from domains.platform.tenants.models import Branch
from domains.platform.users.models import User


class ScopeError(PermissionError):
    """Ни одного доступного филиала в выборке."""


@dataclass(frozen=True)
class Scope:
    organization: object
    # None — вся организация без ограничения (включая записи без филиала:
    # заявка, ещё не распределённая по филиалам).
    branch_ids: tuple | None
    branches: list = field(default_factory=list, compare=False)

    @property
    def cache_key(self) -> str:
        ids = "all" if self.branch_ids is None else ",".join(sorted(map(str, self.branch_ids)))
        return f"{self.organization.pk}:{ids}"

    def filter(self, qs, branch_field: str):
        """Фильтр по филиалу для любого queryset: `branch_field` — путь до
        branch_id от модели («subscription__branch_id», «lesson__group__branch_id»)."""
        if self.branch_ids is None:
            return qs
        return qs.filter(**{f"{branch_field}__in": self.branch_ids})


def allowed_branch_ids(user) -> list | None:
    """None — все филиалы организации."""
    if user.role == User.Role.OWNER:
        return None
    own = list(user.branches.values_list("id", flat=True))
    return own or None


def scope_for(request) -> Scope:
    """?branch=<id>&branch=<id> — несколько филиалов; без параметра —
    филиал из шапки (X-Branch-Id), без него — все доступные."""
    user = request.user
    organization = user.organization
    allowed = allowed_branch_ids(user)
    requested = []
    for raw in request.query_params.getlist("branch"):
        try:
            requested.append(uuid.UUID(raw))
        except ValueError:
            continue
    if not requested:
        active = get_active_branch(request)
        requested = [active.id] if active is not None else []

    if requested:
        ids = [b for b in requested if allowed is None or b in allowed]
    else:
        ids = allowed
    branches = Branch.objects.for_tenant(organization).order_by("name")
    if ids is not None:
        branches = branches.filter(pk__in=ids)
        ids = tuple(branch.pk for branch in branches)
        if not ids:
            raise ScopeError("Нет доступа к выбранным филиалам.")
    return Scope(organization, ids, list(branches))
