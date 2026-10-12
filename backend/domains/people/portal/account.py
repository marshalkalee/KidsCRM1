"""
Аккаунт родителя (TRU-136): дети с филиалами и группами, профиль.
Правила доступа — docs/parent-portal.md.

Родитель в кабинете не меняет данные ребёнка: всё, что про ребёнка, —
через администратора. Сам он правит только свой email, язык кабинета и
пароль (auth.change_password). Номер телефона — логин кабинета — меняет
администратор в карточке родителя (Д40).
"""

from django.db import transaction

from domains.platform.core.audit import AuditLog
from domains.scheduling.groups.models import GroupMembership

from . import access
from .auth import LoginError

LANGUAGES = {"ru", "kk"}

# Что родитель видит о ребёнке (TRU-141, docs/parent-portal.md). Тест
# проверяет, что ответ не шире этого списка: новое поле — сначала сюда и
# в документ, после согласования с центром. Не входят: медицинские
# заметки, причина ухода, согласие на обработку, записи сотрудников.
CHILD_FIELDS = (
    "id",
    "full_name",
    "birth_date",
    "age",
    "status",
    "photo_url",
    "organization",
    "branches",
    "groups",
)


def child_summary(child, memberships):
    groups = [
        {
            "id": str(m.group_id),
            "name": m.group.name,
            "branch": m.group.branch.name if m.group.branch_id else "",
            "direction": m.group.direction.name if m.group.direction_id else "",
        }
        for m in memberships
    ]
    return {
        "id": str(child.id),
        "full_name": child.full_name,
        "birth_date": child.birth_date,
        "age": child.age,
        "status": child.status,
        "photo_url": child.photo_url or "",
        "organization": {"id": str(child.organization_id), "name": child.organization.name},
        "branches": sorted({g["branch"] for g in groups if g["branch"]}),
        "groups": groups,
    }


def children(account):
    kids = list(access.children_for_phone(account.phone))
    memberships = (
        GroupMembership.objects.filter(child__in=kids, left_at__isnull=True)
        .select_related("group__branch", "group__direction")
        .order_by("joined_at")
    )
    by_child = {}
    for membership in memberships:
        by_child.setdefault(membership.child_id, []).append(membership)
    # Сначала те, кто ходит; ушедшие — в конце списка, но видны.
    kids.sort(key=lambda c: (c.status == "left", c.full_name))
    return [child_summary(child, by_child.get(child.id, [])) for child in kids]


def profile(account):
    contacts = list(access.contacts_for_phone(account.phone).select_related("organization"))
    names = sorted({c.full_name for c in contacts})
    emails = sorted({c.email for c in contacts if c.email})
    return {
        "phone": account.phone,
        "language": account.language,
        "full_name": names[0] if names else "",
        "email": emails[0] if emails else "",
        "centers": sorted({c.organization.name for c in contacts}),
    }


@transaction.atomic
def update_profile(account, *, email=None, language=None):
    if language is not None:
        if language not in LANGUAGES:
            raise LoginError("Язык: ru или kk.")
        account.language = language
        account.save(update_fields=["language"])
    if email is not None:
        email = email.strip()
        if email and ("@" not in email or len(email) > 254):
            raise LoginError("Проверьте email.")
        for contact in access.contacts_for_phone(account.phone):
            if contact.email != email:
                before = {"email": contact.email}
                contact.email = email
                contact.save(update_fields=["email", "updated_at"])
                AuditLog.record(
                    actor=None,
                    action=AuditLog.Action.UPDATE,
                    entity=contact,
                    before=before,
                    after={"email": email, "by": "parent_portal"},
                )
    return profile(account)
