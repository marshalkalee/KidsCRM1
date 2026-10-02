"""
Аккаунт родителя (TRU-136): дети с филиалами и группами, профиль, смена
телефона. Правила доступа — docs/parent-portal.md.

Родитель в кабинете не меняет данные ребёнка: всё, что про ребёнка, —
через администратора. Сам он правит только свой email, язык кабинета и
номер телефона (через код на новый номер).
"""

from django.db import transaction
from django.utils import timezone

from domains.people.clients.models import ContactPhone, ParentContact
from domains.platform.core.audit import AuditLog
from domains.scheduling.groups.models import GroupMembership

from . import access
from .auth import (
    LoginError,
    _consume,
    _issue_code,
    _log,
    normalize,
)
from .models import OtpChallenge, ParentAccessLog, ParentAccount

LANGUAGES = {"ru", "kk"}


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


def request_phone_change(account, raw_phone, request_meta):
    phone = normalize(raw_phone)
    if phone == account.phone:
        raise LoginError("Это ваш текущий номер.")
    if ParentAccount.objects.filter(phone=phone).exists():
        # Номер уже входит в кабинет — объединять аккаунты сам родитель не может.
        raise LoginError(
            "Этот номер уже используется для входа. Обратитесь к администратору центра."
        )
    # Код уходит всегда: номер новый, его ещё нет в базе — в этом и смысл.
    _issue_code(
        phone,
        request_meta,
        purpose=OtpChallenge.Purpose.PHONE_CHANGE,
        send=True,
        account=account,
    )
    return {"phone": phone}


def confirm_phone_change(account, raw_phone, code, request_meta):
    phone = normalize(raw_phone)
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    with transaction.atomic():
        outcome = _confirm(account, phone, code, request_meta)
    if isinstance(outcome, LoginError):
        raise outcome
    return outcome


def _confirm(account, phone, code, request_meta):
    challenge = (
        OtpChallenge.objects.select_for_update()
        .filter(
            phone=phone,
            account=account,
            purpose=OtpChallenge.Purpose.PHONE_CHANGE,
            used_at__isnull=True,
            expires_at__gt=timezone.now(),
            attempts__lt=5,
        )
        .order_by("-created_at")
        .first()
    )
    error = _consume(challenge, phone, code, request_meta)
    if error:
        return error
    if ParentAccount.objects.filter(phone=phone).exclude(pk=account.pk).exists():
        return LoginError(
            "Этот номер уже используется для входа. Обратитесь к администратору центра."
        )

    old = account.phone
    contacts = list(access.contacts_for_phone(old))
    ContactPhone.objects.filter(
        parent_contact__in=contacts, number=old, deleted_at__isnull=True
    ).update(number=phone, updated_at=timezone.now())
    ParentContact.objects.filter(pk__in=[c.pk for c in contacts], whatsapp=old).update(
        whatsapp=phone, updated_at=timezone.now()
    )
    for contact in contacts:
        AuditLog.record(
            actor=None,
            action=AuditLog.Action.UPDATE,
            entity=contact,
            before={"phone": old},
            after={"phone": phone, "by": "parent_portal"},
        )
    account.phone = phone
    account.save(update_fields=["phone"])
    _log(ParentAccessLog.Event.PHONE_CHANGED, phone, request_meta, account=account)
    return profile(account)
