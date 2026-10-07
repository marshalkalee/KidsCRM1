"""Публичный профиль центра (TRU-179) — владелец заполняет, родитель увидит
в будущем каталоге. Пока не опубликован, наружу не уходит ничего."""

import re

from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response

from domains.platform.core.images import clean_image, delete_image, save_image
from domains.platform.core.permissions import IsOwner
from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number

from .models import CenterProfile

FOLDER = "centers"
MAX_DESCRIPTION = 1000
_INSTAGRAM = re.compile(r"^(?:https?://)?(?:www\.)?instagram\.com/([A-Za-z0-9_.]+)/?.*$|^@?([A-Za-z0-9_.]+)$")


def _profile(organization) -> CenterProfile:
    profile, _ = CenterProfile.objects.get_or_create(organization=organization)
    return profile


def _payload(profile):
    return {
        "description": profile.description,
        "logo_url": profile.logo_url,
        "photo_urls": profile.photo_urls,
        "phone": profile.phone,
        "instagram": profile.instagram,
        "is_published": profile.is_published,
        "max_photos": CenterProfile.MAX_PHOTOS,
        "organization_name": profile.organization.name,
    }


def normalize_instagram(value: str) -> str:
    """«https://instagram.com/trueballet/», «@trueballet» → «trueballet»."""
    value = (value or "").strip()
    if not value:
        return ""
    match = _INSTAGRAM.match(value)
    if not match:
        raise ValueError("Укажите ник или ссылку на Instagram.")
    return match.group(1) or match.group(2)


@api_view(["GET", "PATCH"])
@permission_classes([IsOwner])
def center_profile(request, version=None):
    profile = _profile(request.user.organization)
    if request.method == "PATCH":
        data, errors = request.data, {}
        if "description" in data:
            text = (data.get("description") or "").strip()
            if len(text) > MAX_DESCRIPTION:
                errors["description"] = [f"Не больше {MAX_DESCRIPTION} символов."]
            profile.description = text
        if "phone" in data:
            try:
                profile.phone = normalize_phone_number(data["phone"]) if data["phone"] else ""
            except InvalidPhoneNumberError:
                errors["phone"] = ["Неверный номер."]
        if "instagram" in data:
            try:
                profile.instagram = normalize_instagram(data["instagram"])
            except ValueError as exc:
                errors["instagram"] = [str(exc)]
        if "is_published" in data:
            if data["is_published"] and not (profile.description or data.get("description")):
                errors["is_published"] = ["Сначала напишите пару строк о центре."]
            profile.is_published = bool(data["is_published"])
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)
        profile.save()
    return Response(_payload(profile))


@api_view(["POST", "DELETE"])
@permission_classes([IsOwner])
@parser_classes([MultiPartParser, JSONParser])
def center_logo(request, version=None):
    profile = _profile(request.user.organization)
    old = profile.logo_url
    if request.method == "POST":
        uploaded, error = clean_image(request.FILES)
        if error:
            return Response({"file": [error]}, status=status.HTTP_400_BAD_REQUEST)
        profile.logo_url = save_image(request, uploaded, FOLDER)
    else:
        profile.logo_url = ""
    profile.save(update_fields=["logo_url", "updated_at"])
    if old:
        delete_image(old, FOLDER)
    return Response(_payload(profile))


@api_view(["POST", "DELETE"])
@permission_classes([IsOwner])
@parser_classes([MultiPartParser, JSONParser])
def center_photos(request, version=None):
    profile = _profile(request.user.organization)
    if request.method == "POST":
        if len(profile.photo_urls) >= CenterProfile.MAX_PHOTOS:
            return Response(
                {"file": [f"Не больше {CenterProfile.MAX_PHOTOS} фото — удалите одно."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        uploaded, error = clean_image(request.FILES)
        if error:
            return Response({"file": [error]}, status=status.HTTP_400_BAD_REQUEST)
        profile.photo_urls = [*profile.photo_urls, save_image(request, uploaded, FOLDER)]
    else:
        url = request.data.get("url", "")
        if url in profile.photo_urls:
            profile.photo_urls = [u for u in profile.photo_urls if u != url]
            delete_image(url, FOLDER)
    profile.save(update_fields=["photo_urls", "updated_at"])
    return Response(_payload(profile))
