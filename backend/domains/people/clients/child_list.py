"""
Список детей с фильтрами/сортировкой/пагинацией — общий для старой
веб-страницы (web_views.child_list_data) и API frontend2
(views.child_table_api, TRU-81). Одна реализация, чтобы два экрана не
разошлись в том, кого считать должником или в каком филиале ребёнок.
"""

from decimal import Decimal

from domains.money.subscriptions.debt import debt_by_child, debtor_child_ids
from domains.money.subscriptions.models import Subscription
from domains.money.subscriptions.renewals import expiring_child_ids
from domains.scheduling.groups.models import GroupMembership

from .models import Child

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

CHILD_SORT_FIELDS = {
    "full_name": "full_name",
    "age": "birth_date",
    "status": "status",
}

# Фильтры, раскрывающие деньги (пусть и без суммы) — только для ролей
# с can_view_client_money.
MONEY_FILTERS = ("has_debt", "expiring")


def branch_names(child, group_branches=None):
    """Филиал не хранится на Child напрямую. Главный источник — филиалы
    групп, где ребёнок сейчас занимается (group_branches, TRU-89): направление
    обычно доступно в нескольких филиалах, и по нему ребёнок «числился» бы
    во всех сразу. Нет групп — филиалы, где доступны его направления."""
    names = set(group_branches or ()) or {
        branch.name for direction in child.directions.all() for branch in direction.branches.all()
    }
    return ", ".join(sorted(names)) if names else None


def active_group_branch_names(child):
    """Филиалы текущих групп ребёнка — из prefetch_related(
    "group_memberships__group__branch"), без запроса на ребёнка."""
    return [
        membership.group.branch.name
        for membership in child.group_memberships.all()
        if membership.left_at is None
    ]


def direction_names(child):
    names = {direction.name for direction in child.directions.all()}
    return ", ".join(sorted(names)) if names else None


def sort_children(qs, sort, direction):
    # Только скалярные поля Child — филиал/направление/группа/абонемент/
    # долг многозначны (M2M/через другую таблицу) или требуют коррелирующих
    # подзапросов, сортировка по ним сюда не входит.
    field = CHILD_SORT_FIELDS.get(sort, "full_name")
    descending = direction == "desc"
    if sort == "age":
        # Возраст не хранится (Child.age — вычисляемое свойство, не
        # колонка БД) — сортируем по birth_date, направление обратное:
        # старше = раньше родился, т.е. "возраст по убыванию" — это
        # "дата рождения по возрастанию".
        descending = not descending
    ordering = f"-{field}" if descending else field
    # pk — стабильный tie-break: без него строки с одинаковым значением
    # сортируемого поля могут менять порядок между запросами соседних
    # страниц (LIMIT/OFFSET без полного порядка не гарантирует стабильность).
    return qs.order_by(ordering, "pk")


def filter_children(qs, organization, params):
    """Шесть фильтров ТЗ п. 4.1 (+ поиск по имени), комбинируются между собой (AND). Долг/
    абонемент — через domains.money.subscriptions (debtor_child_ids/
    expiring_child_ids), не своей копией арифметики: иначе этот список и
    будущие экраны Bekzat'а («Задолженности»/«Продления») разойдутся."""
    needs_distinct = False

    # Поиск по имени прямо в списке (frontend2) — телефон родителя ищется
    # глобальным поиском в шапке, здесь только ФИО ребёнка.
    query = (params.get("q") or "").strip()
    if query:
        qs = qs.filter(full_name__icontains=query)

    branch_id = params.get("branch")
    if branch_id:
        # Как branch_names: ребёнок в группе этого филиала — или с
        # направлением, доступным в нём. Один подзапрос с UNION: OR двух
        # join'ов или двух IN на 5000 детях не укладывается в бюджет.
        in_branch_group = GroupMembership.objects.filter(
            group__branch_id=branch_id, left_at__isnull=True
        ).values("child_id")
        # Направления — только для детей без текущей группы, как в branch_names.
        with_branch_direction = (
            Child.directions.through.objects.filter(direction__branches__id=branch_id)
            .exclude(
                child_id__in=GroupMembership.objects.filter(left_at__isnull=True).values("child_id")
            )
            .values("child_id")
        )
        qs = qs.filter(id__in=in_branch_group.union(with_branch_direction))

    direction_id = params.get("direction")
    if direction_id:
        qs = qs.filter(directions__id=direction_id)
        needs_distinct = True

    group_id = params.get("group")
    if group_id:
        qs = qs.filter(
            group_memberships__group_id=group_id, group_memberships__left_at__isnull=True
        )
        needs_distinct = True

    status = params.get("status")
    if status in Child.Status.values:
        qs = qs.filter(status=status)

    if params.get("has_debt") == "1":
        qs = qs.filter(id__in=debtor_child_ids(organization))

    if params.get("expiring") == "1":
        qs = qs.filter(id__in=expiring_child_ids(organization))

    return qs.distinct() if needs_distinct else qs


def batch_child_extras(organization, child_ids):
    """Группа/абонемент/долг для страницы детей — батчем на весь список
    child_ids, не запросом на каждую строку (ТЗ п. 10.2: иначе 50 строк на
    странице превращаются в 100+ запросов, и бюджет ≤1с не выдерживается)."""
    memberships = (
        GroupMembership.objects.for_tenant(organization)
        .filter(child_id__in=child_ids, left_at__isnull=True)
        .select_related("group__branch")
    )
    groups_by_child = {}
    branches_by_child = {}
    for membership in memberships:
        groups_by_child.setdefault(membership.child_id, []).append(membership.group.name)
        branches_by_child.setdefault(membership.child_id, []).append(membership.group.branch.name)

    subscriptions = (
        Subscription.objects.for_tenant(organization)
        .filter(child_id__in=child_ids)
        .select_related("subscription_type_version")
        .order_by("child_id", "-starts_on")
    )
    # Отсортированы по (child_id, -starts_on) — первое вхождение на child_id
    # — самый свежий абонемент, без лишнего запроса с MAX(starts_on)/DISTINCT.
    latest_subscription_by_child = {}
    for sub in subscriptions:
        latest_subscription_by_child.setdefault(sub.child_id, sub)

    # Сумма долга — сервисом домена «Деньги», не своим подсчётом: та же
    # цифра в карточке родителя и на экране задолженностей.
    return (
        groups_by_child,
        branches_by_child,
        latest_subscription_by_child,
        debt_by_child(organization, child_ids),
    )


def _int_param(params, name, default):
    try:
        return int(params.get(name, default))
    except (TypeError, ValueError):
        return default


def list_children(organization, params, *, show_money):
    """Страница списка: (rows, total). params — QueryDict/dict с фильтрами,
    sort/dir и page/page_size. Без show_money денежные колонки — None, а
    денежные фильтры игнорируются."""
    if not show_money:
        params = {key: value for key, value in params.items() if key not in MONEY_FILTERS}

    qs = Child.objects.for_tenant(organization).prefetch_related("directions__branches")
    qs = filter_children(qs, organization, params)
    qs = sort_children(qs, params.get("sort", "full_name"), params.get("dir", "asc"))

    page = max(1, _int_param(params, "page", 1))
    # Верхняя граница — не даёт с фронта произвольным page_size вернуться
    # к "отдать всё разом".
    page_size = min(max(1, _int_param(params, "page_size", DEFAULT_PAGE_SIZE)), MAX_PAGE_SIZE)

    total = qs.count()
    start = (page - 1) * page_size
    children = list(qs[start : start + page_size])

    child_ids = [child.id for child in children]
    groups_by_child, branches_by_child, subscription_by_child, debts = batch_child_extras(
        organization, child_ids
    )

    rows = []
    for child in children:
        subscription = subscription_by_child.get(child.id)
        rows.append(
            {
                "id": str(child.id),
                "full_name": child.full_name,
                "age": child.age,
                "birth_date": child.birth_date.isoformat(),
                "photo_url": child.photo_url or None,
                "branch_names": branch_names(child, branches_by_child.get(child.id)) or "—",
                "direction_names": direction_names(child) or "—",
                "group_names": ", ".join(groups_by_child.get(child.id, [])) or "—",
                "status": child.status,
                "subscription_name": (
                    subscription.subscription_type_version.name
                    if show_money and subscription
                    else None
                ),
                "debt": str(debts.get(child.id, Decimal(0))) if show_money else None,
            }
        )
    return rows, total
