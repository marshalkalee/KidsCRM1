"""
«О центре» в кабинете родителя: что центр рассказывает о себе (профиль
центра, TRU-179), филиалы с адресом, картой, часами и WhatsApp (TRU-178) и
группы ребёнка с описанием «что взять с собой».

Профиль (описание, логотип, фото, Instagram) — только опубликованный: на
экране владельца сказано «пока профиль не опубликован, его никто не видит».
Адреса, телефоны и часы филиалов родителю нужны всегда — они показываются
и без профиля (Д39).
"""

from urllib.parse import quote

from domains.platform.public_api.models import CenterProfile
from domains.scheduling.groups.models import GroupMembership


def _digits(phone: str) -> str:
    return "".join(ch for ch in phone or "" if ch.isdigit())


def _map_url(branch) -> str:
    """Ссылка на 2GIS: точка, если она есть, иначе поиск по адресу."""
    if branch.latitude is not None and branch.longitude is not None:
        return f"https://2gis.kz/geo/{branch.longitude},{branch.latitude}"
    query = ", ".join(part for part in (branch.city, branch.address) if part)
    return f"https://2gis.kz/search/{quote(query)}" if query else ""


def _profile(organization):
    profile = CenterProfile.objects.filter(organization=organization, is_published=True).first()
    if profile is None:
        return None
    return {
        "description": profile.description,
        "logo_url": profile.logo_url,
        "photo_urls": list(profile.photo_urls or []),
        "phone": profile.phone,
        "whatsapp_url": f"https://wa.me/{_digits(profile.phone)}" if profile.phone else "",
        "instagram": profile.instagram,
        "instagram_url": f"https://instagram.com/{profile.instagram}" if profile.instagram else "",
    }


def center(child) -> dict:
    organization = child.organization
    memberships = list(
        GroupMembership.objects.filter(
            child=child, left_at__isnull=True, deleted_at__isnull=True
        ).select_related("group__branch", "group__direction")
    )
    mine = {m.group.branch_id for m in memberships if m.group.branch_id}
    branches = sorted(
        organization.branch_set.filter(deleted_at__isnull=True, is_active=True),
        key=lambda b: (b.id not in mine, b.name),
    )
    return {
        "name": organization.name,
        "profile": _profile(organization),
        "branches": [
            {
                "id": str(branch.id),
                "name": branch.name,
                "city": branch.city,
                "district": branch.district,
                "address": branch.address,
                "phone": branch.phone,
                "whatsapp_url": f"https://wa.me/{_digits(branch.phone)}" if branch.phone else "",
                "working_hours": branch.working_hours or {},
                "map_url": _map_url(branch),
                "is_childs": branch.id in mine,
            }
            for branch in branches
        ],
        "groups": [
            {
                "name": m.group.name,
                "direction": m.group.direction.name if m.group.direction_id else "",
                "branch": m.group.branch.name if m.group.branch_id else "",
                "description": m.group.description,
            }
            for m in sorted(memberships, key=lambda m: m.group.name)
        ],
    }
