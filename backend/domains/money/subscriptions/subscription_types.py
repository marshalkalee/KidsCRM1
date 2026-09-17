"""
Правка денежно значимых полей типа абонемента (цена, квота/безлимит,
срок, правила) — только через update_rules(): она создаёт версию и
только потом обновляет карточку. Прямой .save() после ручного
присваивания этих полей в обход — баг (см. критерий приёмки TRU-57).

Архивация (is_active) через эту функцию не идёт — это видимость в
get_selectable_subscription_types(), не денежное правило, версию не
создаёт.
"""

from django.db import transaction

from .models import RULES_SCHEMA_VERSION, SubscriptionType, SubscriptionTypeVersion

VERSIONED_FIELDS = ("name", "price", "is_unlimited", "quota_sessions", "duration_days", "rules")


@transaction.atomic
def update_rules(subscription_type: SubscriptionType, **changes) -> SubscriptionTypeVersion:
    for field in changes:
        if field not in VERSIONED_FIELDS:
            raise ValueError(f"{field} не версионируется — используйте .save() напрямую")
        setattr(subscription_type, field, changes[field])

    subscription_type.full_clean()
    subscription_type.save(update_fields=list(changes))

    return SubscriptionTypeVersion.objects.create(
        organization=subscription_type.organization,
        subscription_type=subscription_type,
        schema_version=RULES_SCHEMA_VERSION,
        **{f: getattr(subscription_type, f) for f in VERSIONED_FIELDS},
    )

def create_type(organization, *, name, price, is_unlimited=False, quota_sessions=None,
                 duration_days, rules=None, directions=(), branches=()) -> "SubscriptionType":
    """Создаёт тип и сразу его первую версию — без этого Subscription
    не на что сослаться (найдено при проектировании TRU-58)."""
    st = SubscriptionType.objects.create(
        organization=organization, name=name, price=price, is_unlimited=is_unlimited,
        quota_sessions=quota_sessions, duration_days=duration_days, rules=rules or {},
    )
    if directions:
        st.directions.set(directions)
    if branches:
        st.branches.set(branches)
    SubscriptionTypeVersion.objects.create(
        organization=organization, subscription_type=st, schema_version=RULES_SCHEMA_VERSION,
        name=st.name, price=st.price, is_unlimited=st.is_unlimited,
        quota_sessions=st.quota_sessions, duration_days=st.duration_days, rules=st.rules,
    )
    return st

def get_selectable_subscription_types(organization, branch=None):
    """См. tenants.directions.get_selectable_directions — тот же принцип:
    не предлагать архивные типы при продаже нового абонемента (TRU-57),
    но не трогать уже проданные (они хранят версию, не тип)."""
    qs = SubscriptionType.objects.for_tenant(organization).filter(is_active=True)
    if branch is not None:
        qs = qs.filter(branches=branch)
    return qs.order_by("name")